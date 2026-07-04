import calendar
from datetime import date, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models.usuario import Role, Usuario
from models.venda_historico import VendaHistorico
from models.venda_semana import VendaSemana
from services.sheets import (
    DIAS_SEMANA,
    get_aba_venda_atual,
    get_lista_diaria,
    get_vendas_semana as sheets_get_vendas_semana,
    normaliza,
)

router = APIRouter()


# ── Pydantic models ──────────────────────────────────────────────────────────


class VendedorItem(BaseModel):
    nome: str
    nome_planilha: str


class VendedoresListResponse(BaseModel):
    vendedores: list[VendedorItem]


class ClienteCarteira(BaseModel):
    cliente: str
    comprou_mes: bool
    ultima_compra: Optional[date]


class CarteiraResponse(BaseModel):
    compraram: int
    nao_compraram: int
    clientes: list[ClienteCarteira]


class FollowUpResponse(BaseModel):
    dia_semana: str
    clientes: list[str]


class ClienteFiado(BaseModel):
    cliente: str
    valor_aberto: float


class FiadoResponse(BaseModel):
    clientes: list[ClienteFiado]
    total: float


class MargemResponse(BaseModel):
    faturamento: float
    custo: float
    margem_valor: float
    margem_pct: float
    semana_ref: str


# ── Helpers ──────────────────────────────────────────────────────────────────


def _resolve(current_user: Usuario, vendedor: Optional[str]) -> str:
    if current_user.role == Role.vendedor:
        return current_user.nome_planilha or current_user.nome
    if not vendedor:
        raise HTTPException(status_code=400, detail="Parâmetro 'vendedor' obrigatório.")
    return vendedor


def _filtro_vendedor(nome: str):
    return func.upper(func.trim(VendaSemana.vendedor)) == nome.upper().strip()


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("", response_model=VendedoresListResponse)
def listar_vendedores(
    current_user: Annotated[Usuario, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    usuarios = (
        db.query(Usuario)
        .filter(Usuario.role == Role.vendedor, Usuario.ativo == True)
        .all()
    )
    return VendedoresListResponse(
        vendedores=[
            VendedorItem(nome=u.nome, nome_planilha=u.nome_planilha or u.nome)
            for u in usuarios
        ]
    )


@router.get("/carteira", response_model=CarteiraResponse)
def carteira(
    current_user: Annotated[Usuario, Depends(get_current_user)],
    db: Session = Depends(get_db),
    vendedor: Optional[str] = Query(default=None),
    mes: Optional[str] = Query(default=None, description="YYYY-MM"),
):
    nome = _resolve(current_user, vendedor)

    hoje = date.today()
    mes_ref = mes or hoje.strftime("%Y-%m")
    ano, mm = map(int, mes_ref.split("-"))
    inicio = date(ano, mm, 1)
    fim = date(ano, mm, calendar.monthrange(ano, mm)[1])

    todos = {
        row.cliente
        for row in db.query(VendaSemana.cliente)
        .filter(_filtro_vendedor(nome))
        .distinct()
        .all()
    }

    compraram_rows = (
        db.query(VendaSemana.cliente, func.max(VendaSemana.data).label("ultima"))
        .filter(
            _filtro_vendedor(nome),
            VendaSemana.data >= inicio,
            VendaSemana.data <= fim,
        )
        .group_by(VendaSemana.cliente)
        .all()
    )
    compraram = {row.cliente: row.ultima for row in compraram_rows}

    clientes = [
        ClienteCarteira(
            cliente=c,
            comprou_mes=c in compraram,
            ultima_compra=compraram.get(c),
        )
        for c in sorted(todos)
    ]

    return CarteiraResponse(
        compraram=len(compraram),
        nao_compraram=len(todos) - len(compraram),
        clientes=clientes,
    )


@router.get("/nao-pegaram-hoje", response_model=FollowUpResponse)
def nao_pegaram_hoje(
    current_user: Annotated[Usuario, Depends(get_current_user)],
    db: Session = Depends(get_db),
    vendedor: Optional[str] = Query(default=None),
):
    nome = _resolve(current_user, vendedor)
    aba_hoje = get_aba_venda_atual()

    clientes_db = [
        row.cliente
        for row in db.query(VendaSemana.cliente)
        .filter(_filtro_vendedor(nome), VendaSemana.dia_semana == aba_hoje)
        .distinct()
        .all()
    ]
    # Mapa: nome_normalizado → nome_original (para exibição)
    historico_norm = {normaliza(c): c for c in clientes_db}

    try:
        live = sheets_get_vendas_semana(nome_vendedor=None, bust=False)
        hoje_vivo = {
            normaliza(v["cliente"])
            for v in live
            if v.get("dia") == aba_hoje
        }
    except Exception:
        hoje_vivo = set()

    nao_pegaram = [
        nome_original
        for norm, nome_original in historico_norm.items()
        if norm not in hoje_vivo
    ]

    return FollowUpResponse(
        dia_semana=aba_hoje,
        clientes=sorted(nao_pegaram),
    )


@router.get("/fiado", response_model=FiadoResponse)
def fiado_vendedor(
    current_user: Annotated[Usuario, Depends(get_current_user)],
    db: Session = Depends(get_db),
    vendedor: Optional[str] = Query(default=None),
):
    nome = _resolve(current_user, vendedor)

    clientes_raw = [
        row.cliente
        for row in db.query(VendaSemana.cliente)
        .filter(_filtro_vendedor(nome))
        .distinct()
        .all()
    ]

    if not clientes_raw:
        return FiadoResponse(clientes=[], total=0.0)

    clientes_upper = [c.upper().strip() for c in clientes_raw]

    fiado_rows = (
        db.query(
            VendaHistorico.cliente,
            func.sum(VendaHistorico.valor_aberto).label("total_aberto"),
        )
        .filter(
            func.upper(func.trim(VendaHistorico.cliente)).in_(clientes_upper),
            VendaHistorico.valor_aberto > 0,
        )
        .group_by(VendaHistorico.cliente)
        .order_by(func.sum(VendaHistorico.valor_aberto).desc())
        .all()
    )

    total = sum(float(row.total_aberto or 0) for row in fiado_rows)

    return FiadoResponse(
        clientes=[
            ClienteFiado(
                cliente=row.cliente,
                valor_aberto=float(row.total_aberto or 0),
            )
            for row in fiado_rows
        ],
        total=total,
    )


@router.get("/margem", response_model=MargemResponse)
def margem_vendedor(
    current_user: Annotated[Usuario, Depends(get_current_user)],
    db: Session = Depends(get_db),
    vendedor: Optional[str] = Query(default=None),
):
    nome = _resolve(current_user, vendedor)

    hoje = date.today()
    semana_ref = hoje - timedelta(days=hoje.weekday())

    fat_row = (
        db.query(func.sum(VendaSemana.faturamento_estimado).label("total"))
        .filter(_filtro_vendedor(nome), VendaSemana.semana_ref == semana_ref)
        .first()
    )
    faturamento = float(fat_row.total or 0)

    qtde_rows = (
        db.query(
            VendaSemana.produto,
            func.sum(VendaSemana.quantidade).label("total_qtde"),
        )
        .filter(_filtro_vendedor(nome), VendaSemana.semana_ref == semana_ref)
        .group_by(VendaSemana.produto)
        .all()
    )

    custo_total = 0.0
    if qtde_rows:
        try:
            # Os custos são os mesmos em todas as abas — lê SEGUNDA como referência
            lista_diaria = get_lista_diaria(DIAS_SEMANA[1])
            custo_por_produto = {
                normaliza(item["produto"]): float(
                    str(item["valor"]).replace(",", ".")
                )
                for item in lista_diaria
                if item.get("valor")
            }
            for row in qtde_rows:
                custo_unit = custo_por_produto.get(normaliza(row.produto), 0.0)
                custo_total += float(row.total_qtde or 0) * custo_unit
        except Exception:
            custo_total = 0.0

    margem_valor = faturamento - custo_total
    margem_pct = (margem_valor / faturamento * 100) if faturamento > 0 else 0.0

    return MargemResponse(
        faturamento=round(faturamento, 2),
        custo=round(custo_total, 2),
        margem_valor=round(margem_valor, 2),
        margem_pct=round(margem_pct, 2),
        semana_ref=str(semana_ref),
    )
