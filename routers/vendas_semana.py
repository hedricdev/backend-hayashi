from datetime import date, datetime, timedelta
from typing import Annotated, Optional

import pytz
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models.usuario import Role, Usuario
from models.venda_semana import VendaSemana
from services.sheets import get_vendas_semana

router = APIRouter()

DIA_TO_OFFSET = {
    "SEGUNDA": 0,
    "TERÇA": 1,
    "QUARTA": 2,
    "QUINTA": 3,
    "SEXTA": 4,
    "SABADO": 5,
}


def _precos_list(preco: str) -> list[float]:
    out: list[float] = []
    for parte in (preco or "").replace(",", ".").split("/"):
        try:
            out.append(float(parte.strip()))
        except ValueError:
            pass
    return out


# ── Pydantic ────────────────────────────────────────────────────────────────

class ImportarResponse(BaseModel):
    importados: int
    semana_ref: str


class SemanaDisponivel(BaseModel):
    semana_ref: str
    label: str


class ProdutoItem(BaseModel):
    nome: str
    quantidade: int


class VendaItem(BaseModel):
    cliente: str
    vendedor: str
    pagamento: str
    preco: str
    produtos: list[ProdutoItem]
    dia: str
    data: Optional[str] = None  # ISO date — presente nas respostas do banco


class VendasSemanaResponse(BaseModel):
    vendas: list[VendaItem]
    semana_ref: str


class VendedorPerformance(BaseModel):
    nome: str
    faturamento: float
    caixas: int
    num_vendas: int
    num_clientes: int


class VendedoresPerformanceResponse(BaseModel):
    vendedores: list[VendedorPerformance]
    data_inicio: str
    data_fim: str


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/importar", response_model=ImportarResponse)
def importar_planilha(
    current_user: Annotated[Usuario, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    if current_user.role != Role.admin:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")

    brasilia = pytz.timezone("America/Sao_Paulo")
    hoje = datetime.now(brasilia).date()
    semana_ref = hoje - timedelta(days=hoje.weekday())

    # Lê planilha ao vivo (bust=True para ignorar cache)
    vendas_raw = get_vendas_semana(bust=True)

    # Limpa semana anterior para permitir re-importação
    db.query(VendaSemana).filter(VendaSemana.semana_ref == semana_ref).delete()

    importados = 0
    for v in vendas_raw:
        dia = v["dia"]
        offset = DIA_TO_OFFSET.get(dia, 0)
        data_venda = semana_ref + timedelta(days=offset)

        produtos = v["produtos"]
        total_caixas = sum(p["quantidade"] for p in produtos)
        precos = _precos_list(v["preco"])
        total_fat = sum(precos)

        for idx, p in enumerate(produtos):
            if len(precos) == len(produtos):
                fat = precos[idx]
            elif total_caixas > 0:
                fat = total_fat * (p["quantidade"] / total_caixas)
            else:
                fat = 0.0

            row = VendaSemana(
                semana_ref=semana_ref,
                data=data_venda,
                dia_semana=dia,
                vendedor=v["vendedor"],
                cliente=v["cliente"],
                produto=p["nome"],
                quantidade=p["quantidade"],
                pagamento=v["pagamento"] or None,
                faturamento_estimado=round(fat, 2) if fat else None,
            )
            db.add(row)
            importados += 1

    db.commit()
    return {"importados": importados, "semana_ref": str(semana_ref)}


@router.get("/semanas", response_model=list[SemanaDisponivel])
def list_semanas(
    _: Annotated[Usuario, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    rows = (
        db.query(VendaSemana.semana_ref)
        .distinct()
        .order_by(VendaSemana.semana_ref.desc())
        .all()
    )
    result = []
    for (semana_ref,) in rows:
        sabado = semana_ref + timedelta(days=5)
        result.append(
            SemanaDisponivel(
                semana_ref=str(semana_ref),
                label=f"{semana_ref.strftime('%d/%m')} – {sabado.strftime('%d/%m/%Y')}",
            )
        )
    return result


@router.get("", response_model=VendasSemanaResponse)
def get_vendas_db(
    _: Annotated[Usuario, Depends(get_current_user)],
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    vendedor: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(VendaSemana)
    if data_inicio:
        q = q.filter(VendaSemana.data >= data_inicio)
    if data_fim:
        q = q.filter(VendaSemana.data <= data_fim)
    if vendedor:
        q = q.filter(VendaSemana.vendedor == vendedor)
    rows = q.order_by(VendaSemana.data, VendaSemana.cliente, VendaSemana.vendedor).all()

    # Reagrupa linhas normalizadas de volta em "vendas" (uma por data/cliente/vendedor)
    vendas_map: dict[tuple, dict] = {}
    for row in rows:
        key = (str(row.data), row.dia_semana, row.vendedor, row.cliente, row.pagamento or "")
        if key not in vendas_map:
            vendas_map[key] = {
                "cliente": row.cliente,
                "vendedor": row.vendedor,
                "pagamento": row.pagamento or "",
                "produtos": [],
                "dia": row.dia_semana,
                "data": str(row.data),
                "total_fat": 0.0,
            }
        vendas_map[key]["produtos"].append(
            ProdutoItem(nome=row.produto, quantidade=row.quantidade)
        )
        vendas_map[key]["total_fat"] += float(row.faturamento_estimado or 0)

    vendas = [
        VendaItem(
            cliente=v["cliente"],
            vendedor=v["vendedor"],
            pagamento=v["pagamento"],
            preco=str(round(v["total_fat"], 2)),
            produtos=v["produtos"],
            dia=v["dia"],
            data=v["data"],
        )
        for v in vendas_map.values()
    ]

    return VendasSemanaResponse(vendas=vendas, semana_ref="")


@router.get("/performance", response_model=VendedoresPerformanceResponse)
def get_vendedores_performance(
    _: Annotated[Usuario, Depends(get_current_user)],
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    db: Session = Depends(get_db),
):
    brasilia = pytz.timezone("America/Sao_Paulo")
    hoje = datetime.now(brasilia).date()
    if hoje.month == 12:
        fim_mes = date(hoje.year + 1, 1, 1) - timedelta(days=1)
    else:
        fim_mes = date(hoje.year, hoje.month + 1, 1) - timedelta(days=1)

    primeiro_dia = data_inicio or date(hoje.year, hoje.month, 1)
    ultimo_dia = data_fim or fim_mes

    agg = (
        db.query(
            VendaSemana.vendedor,
            func.sum(VendaSemana.faturamento_estimado).label("faturamento"),
            func.sum(VendaSemana.quantidade).label("caixas"),
        )
        .filter(VendaSemana.data >= primeiro_dia, VendaSemana.data <= ultimo_dia)
        .group_by(VendaSemana.vendedor)
        .all()
    )

    vendas_subq = (
        db.query(VendaSemana.vendedor, VendaSemana.data, VendaSemana.cliente)
        .filter(VendaSemana.data >= primeiro_dia, VendaSemana.data <= ultimo_dia)
        .distinct()
        .subquery()
    )
    vendas_map = {
        r.vendedor: r.num_vendas
        for r in db.query(
            vendas_subq.c.vendedor, func.count().label("num_vendas")
        ).group_by(vendas_subq.c.vendedor).all()
    }

    clientes_subq = (
        db.query(VendaSemana.vendedor, VendaSemana.cliente)
        .filter(VendaSemana.data >= primeiro_dia, VendaSemana.data <= ultimo_dia)
        .distinct()
        .subquery()
    )
    clientes_map = {
        r.vendedor: r.num_clientes
        for r in db.query(
            clientes_subq.c.vendedor, func.count().label("num_clientes")
        ).group_by(clientes_subq.c.vendedor).all()
    }

    vendedores = sorted(
        [
            VendedorPerformance(
                nome=r.vendedor or "—",
                faturamento=round(float(r.faturamento or 0), 2),
                caixas=int(r.caixas or 0),
                num_vendas=vendas_map.get(r.vendedor, 0),
                num_clientes=clientes_map.get(r.vendedor, 0),
            )
            for r in agg
        ],
        key=lambda v: v.faturamento,
        reverse=True,
    )

    return VendedoresPerformanceResponse(
        vendedores=vendedores,
        data_inicio=str(primeiro_dia),
        data_fim=str(ultimo_dia),
    )
