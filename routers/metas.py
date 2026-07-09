import asyncio
import calendar
import threading
from datetime import date, datetime
from typing import Annotated, Optional

import pytz
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models.importacao import Importacao
from models.meta_mensal import MetaMensal
from models.usuario import Role, Usuario
from models.venda_historico import VendaHistorico
from models.venda_semana import VendaSemana
from services.scraping import IFrutiScraper
from services.sse_log import build_sse_runner, importacao_to_dict, make_stream, salvar_no_banco

router = APIRouter()

MES_PT = {
    1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
}


def _f(v) -> float:
    return round(float(v or 0), 2)


def _faturamento_por_mes(db: Session) -> dict[str, float]:
    mes_trunc = func.date_trunc("month", VendaHistorico.data)
    rows = (
        db.query(
            mes_trunc.label("mes_inicio"),
            func.sum(VendaHistorico.total_item).label("fat"),
        )
        .group_by(mes_trunc)
        .all()
    )
    result: dict[str, float] = {}
    for r in rows:
        d = r.mes_inicio.date() if hasattr(r.mes_inicio, "date") else r.mes_inicio
        result[d.strftime("%Y-%m")] = _f(r.fat)
    return result


# ── Pydantic ─────────────────────────────────────────────────────────────────

class MetaInput(BaseModel):
    mes: str            # YYYY-MM
    meta: float
    supermeta: float


class MetaStatus(BaseModel):
    mes: str
    mes_label: str
    meta: float
    supermeta: float
    faturamento: float
    lucro: Optional[float] = None
    usa_lucro: bool
    pct_meta: float
    pct_supermeta: float
    status: str         # "abaixo_meta" | "meta" | "supermeta"
    tem_dados_ifruti: bool


class MetaAtualResponse(BaseModel):
    meta: Optional[MetaStatus] = None
    mes_atual: str


class VendedorContribuicao(BaseModel):
    vendedor: str
    faturamento: float
    pct: float              # % do total da planilha neste mês


class ContribuicaoResponse(BaseModel):
    mes: str
    vendedores: list[VendedorContribuicao]
    total_planilha: float   # soma dos faturamentos da planilha (estimado)
    semanas_salvas: int     # quantas semanas distintas foram salvas no mês


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", response_model=MetaStatus)
def upsert_meta(
    payload: MetaInput,
    current_user: Annotated[Usuario, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    if current_user.role != Role.admin:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")

    row = db.query(MetaMensal).filter(MetaMensal.mes == payload.mes).first()
    if row:
        row.meta = payload.meta
        row.supermeta = payload.supermeta
        row.atualizado_em = datetime.utcnow()
    else:
        row = MetaMensal(
            mes=payload.mes,
            meta=payload.meta,
            supermeta=payload.supermeta,
        )
        db.add(row)
    db.commit()
    db.refresh(row)

    fat_map = _faturamento_por_mes(db)
    fat = fat_map.get(payload.mes, 0.0)
    return _build_status(row, fat)


@router.get("", response_model=list[MetaStatus])
def list_metas(
    _: Annotated[Usuario, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    metas = db.query(MetaMensal).order_by(MetaMensal.mes.desc()).all()
    fat_map = _faturamento_por_mes(db)
    return [_build_status(m, fat_map.get(m.mes, 0.0)) for m in metas]


@router.get("/atual", response_model=MetaAtualResponse)
def get_meta_atual(
    _: Annotated[Usuario, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    brasilia = pytz.timezone("America/Sao_Paulo")
    mes_atual = datetime.now(brasilia).strftime("%Y-%m")

    row = db.query(MetaMensal).filter(MetaMensal.mes == mes_atual).first()
    fat_map = _faturamento_por_mes(db)
    fat = fat_map.get(mes_atual, 0.0)

    return MetaAtualResponse(
        meta=_build_status(row, fat) if row else None,
        mes_atual=mes_atual,
    )


@router.post("/lucro/sync")
def sync_lucro(
    current_user: Annotated[Usuario, Depends(get_current_user)],
    mes: str,
    db: Session = Depends(get_db),
):
    """Sincroniza o lucro do mês sob demanda: login no iFruti, lê o "Lucro do
    período" na tela Administrar Loja > Resultado > DRE e grava na meta do mês.
    """
    if current_user.role != Role.admin:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")

    row = db.query(MetaMensal).filter(MetaMensal.mes == mes).first()
    if not row:
        raise HTTPException(
            status_code=404,
            detail="Cadastre a meta desse mês antes de sincronizar o lucro",
        )

    brasilia = pytz.timezone("America/Sao_Paulo")
    mes_atual = datetime.now(brasilia).strftime("%Y-%m")
    ano, m = int(mes[:4]), int(mes[5:])
    primeiro_dia = date(ano, m, 1)
    ultimo_dia = (
        datetime.now(brasilia).date()
        if mes == mes_atual
        else date(ano, m, calendar.monthrange(ano, m)[1])
    )
    data_inicio = primeiro_dia.strftime("%d/%m/%Y")
    data_fim = ultimo_dia.strftime("%d/%m/%Y")

    msg_queue, messages, iniciado_em, put = build_sse_runner()

    def run_scraper():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _run():
            try:
                put(f"Buscando lucro de {data_inicio} até {data_fim}...")
                async with IFrutiScraper(debug=True) as scraper:
                    put("Login no iFruti...")
                    resultado = await scraper.buscar_lucro_periodo(data_inicio, data_fim)

                from database import SessionLocal
                sync_db = SessionLocal()
                try:
                    linha = sync_db.query(MetaMensal).filter(MetaMensal.mes == mes).first()
                    if linha:
                        linha.lucro = resultado["lucro"]
                        linha.lucro_margem_pct = resultado["margem_pct"]
                        linha.lucro_atualizado_em = datetime.utcnow()
                        sync_db.commit()
                finally:
                    sync_db.close()

                margem = resultado["margem_pct"]
                margem_str = f"{margem:.2f}%".replace(".", ",") if margem is not None else "—"
                lucro_str = f"{resultado['lucro']:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
                put(f"✓ Lucro do período: R$ {lucro_str} ({margem_str})")
            except Exception as e:
                put(f"ERRO: {e}")
            finally:
                msg_queue.put(None)

        loop.run_until_complete(_run())
        loop.close()
        salvar_no_banco(messages, iniciado_em, "lucro_sync")

    threading.Thread(target=run_scraper, daemon=True).start()

    return StreamingResponse(
        make_stream(msg_queue),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/lucro/sync/ultimo-log")
def get_ultimo_log_sync_lucro(
    current_user: Annotated[Usuario, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    importacao = (
        db.query(Importacao)
        .filter(Importacao.tipo == "lucro_sync")
        .order_by(Importacao.id.desc())
        .first()
    )
    if not importacao:
        return {"log": None}
    return importacao_to_dict(importacao)


@router.get("/vendedores", response_model=ContribuicaoResponse)
def get_contribuicao_vendedores(
    _: Annotated[Usuario, Depends(get_current_user)],
    db: Session = Depends(get_db),
    mes: Optional[str] = None,   # YYYY-MM; default = mês atual
):
    if not mes:
        brasilia = pytz.timezone("America/Sao_Paulo")
        mes = datetime.now(brasilia).strftime("%Y-%m")

    # Primeiro dia e último dia do mês
    ano, m = int(mes[:4]), int(mes[5:])
    primeiro_dia = date(ano, m, 1)
    ultimo_dia = date(ano, m, calendar.monthrange(ano, m)[1])

    rows = (
        db.query(
            VendaSemana.vendedor,
            func.sum(VendaSemana.faturamento_estimado).label("fat"),
        )
        .filter(VendaSemana.data >= primeiro_dia, VendaSemana.data <= ultimo_dia)
        .group_by(VendaSemana.vendedor)
        .order_by(func.sum(VendaSemana.faturamento_estimado).desc())
        .all()
    )

    semanas_salvas = (
        db.query(func.count(func.distinct(VendaSemana.semana_ref)))
        .filter(VendaSemana.data >= primeiro_dia, VendaSemana.data <= ultimo_dia)
        .scalar()
        or 0
    )

    total = sum(_f(r.fat) for r in rows)
    vendedores = [
        VendedorContribuicao(
            vendedor=r.vendedor,
            faturamento=_f(r.fat),
            pct=round((_f(r.fat) / total * 100) if total > 0 else 0, 1),
        )
        for r in rows
    ]

    return ContribuicaoResponse(
        mes=mes,
        vendedores=vendedores,
        total_planilha=round(total, 2),
        semanas_salvas=semanas_salvas,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_status(row: MetaMensal, faturamento: float) -> MetaStatus:
    meta = _f(row.meta)
    supermeta = _f(row.supermeta)

    usa_lucro = row.lucro is not None
    valor = _f(row.lucro) if usa_lucro else faturamento

    pct_meta = round((valor / meta * 100) if meta > 0 else 0, 1)
    pct_supermeta = round((valor / supermeta * 100) if supermeta > 0 else 0, 1)

    if valor >= supermeta:
        status = "supermeta"
    elif valor >= meta:
        status = "meta"
    else:
        status = "abaixo_meta"

    # Extrai label do mês
    try:
        ano, m = int(row.mes[:4]), int(row.mes[5:])
        mes_label = f"{MES_PT[m]}/{str(ano)[2:]}"
    except Exception:
        mes_label = row.mes

    return MetaStatus(
        mes=row.mes,
        mes_label=mes_label,
        meta=meta,
        supermeta=supermeta,
        faturamento=faturamento,
        lucro=_f(row.lucro) if usa_lucro else None,
        usa_lucro=usa_lucro,
        pct_meta=pct_meta,
        pct_supermeta=pct_supermeta,
        status=status,
        tem_dados_ifruti=usa_lucro or faturamento > 0,
    )
