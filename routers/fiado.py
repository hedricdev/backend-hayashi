import asyncio
import threading
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models.importacao import Importacao
from models.usuario import Role, Usuario
from models.venda_historico import VendaHistorico
from services.fiado_pdf import gerar_pdf_fiado
from services.fiado_reconcile import reconciliar_fiado
from services.historico_parser import parse_ifruti_xls
from services.scraping import IFrutiScraper
from services.sse_log import build_sse_runner, importacao_to_dict, make_stream, salvar_no_banco

router = APIRouter()


def _f(v) -> float:
    return round(float(v or 0), 2)


def _exigir_admin(current_user: Usuario):
    if current_user.role != Role.admin:
        raise HTTPException(403, "Acesso restrito a administradores")


# ── Pydantic ─────────────────────────────────────────────────────────────────

class FaixaAging(BaseModel):
    label: str
    valor: float
    count: int


class FiadoResumo(BaseModel):
    total_aberto: float
    total_clientes: int
    faixas: list[FaixaAging]


class FiadoCliente(BaseModel):
    nome: str
    total_aberto: float
    vendas_abertas: int
    dias_em_aberto: int  # desde a venda mais antiga ainda aberta


class FiadoVenda(BaseModel):
    id: int
    data: str
    produto: str
    qtde: int
    total_item: float
    valor_aberto: float


# ── Helpers ──────────────────────────────────────────────────────────────────

def _vendas_abertas_cliente(
    db: Session,
    nome: str,
    data_inicio: date | None = None,
    data_fim: date | None = None,
) -> list[VendaHistorico]:
    query = db.query(VendaHistorico).filter(
        VendaHistorico.cliente == nome, VendaHistorico.valor_aberto > 0
    )
    if data_inicio:
        query = query.filter(VendaHistorico.data >= data_inicio)
    if data_fim:
        query = query.filter(VendaHistorico.data <= data_fim)
    return query.order_by(VendaHistorico.data).all()


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/resumo", response_model=FiadoResumo)
def get_resumo(
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _exigir_admin(current_user)

    aging_faixa = case(
        (func.current_date() - VendaHistorico.data <= 7, "Até 7 dias"),
        (func.current_date() - VendaHistorico.data <= 30, "8–30 dias"),
        else_="+30 dias",
    )
    rows_aging = (
        db.query(
            aging_faixa.label("faixa"),
            func.sum(VendaHistorico.valor_aberto).label("valor"),
            func.count(VendaHistorico.id).label("cnt"),
        )
        .filter(VendaHistorico.valor_aberto > 0)
        .group_by(aging_faixa)
        .all()
    )
    ordem = {"Até 7 dias": 0, "8–30 dias": 1, "+30 dias": 2}
    faixas = [
        FaixaAging(label=r.faixa, valor=_f(r.valor), count=r.cnt or 0)
        for r in sorted(rows_aging, key=lambda x: ordem.get(x.faixa, 99))
    ]

    total_aberto = _f(
        db.query(func.sum(VendaHistorico.valor_aberto))
        .filter(VendaHistorico.valor_aberto > 0)
        .scalar()
    )
    total_clientes = (
        db.query(func.count(func.distinct(VendaHistorico.cliente)))
        .filter(VendaHistorico.valor_aberto > 0)
        .scalar()
        or 0
    )

    return FiadoResumo(total_aberto=total_aberto, total_clientes=total_clientes, faixas=faixas)


@router.get("/clientes", response_model=list[FiadoCliente])
def get_clientes(
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _exigir_admin(current_user)

    rows = (
        db.query(
            VendaHistorico.cliente,
            func.sum(VendaHistorico.valor_aberto).label("aberto"),
            func.count(func.distinct(VendaHistorico.data)).label("vendas"),
            func.min(VendaHistorico.data).label("mais_antiga"),
        )
        .filter(VendaHistorico.valor_aberto > 0)
        .group_by(VendaHistorico.cliente)
        .order_by(func.sum(VendaHistorico.valor_aberto).desc())
        .all()
    )

    hoje = date.today()
    return [
        FiadoCliente(
            nome=r.cliente,
            total_aberto=_f(r.aberto),
            vendas_abertas=r.vendas or 0,
            dias_em_aberto=(hoje - r.mais_antiga).days if r.mais_antiga else 0,
        )
        for r in rows
    ]


@router.get("/clientes/{nome}/vendas", response_model=list[FiadoVenda])
def get_vendas_cliente(
    nome: str,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _exigir_admin(current_user)
    vendas = _vendas_abertas_cliente(db, nome, data_inicio, data_fim)
    if not vendas:
        raise HTTPException(404, "Nenhuma venda em aberto para esse cliente no período")
    return [
        FiadoVenda(
            id=v.id,
            data=v.data.isoformat(),
            produto=v.produto,
            qtde=v.qtde,
            total_item=_f(v.total_item),
            valor_aberto=_f(v.valor_aberto),
        )
        for v in vendas
    ]


@router.get("/clientes/{nome}/pdf")
def get_pdf_cliente(
    nome: str,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _exigir_admin(current_user)
    vendas = _vendas_abertas_cliente(db, nome, data_inicio, data_fim)
    if not vendas:
        raise HTTPException(404, "Nenhuma venda em aberto para esse cliente no período")

    pdf_bytes = gerar_pdf_fiado(nome, vendas, data_inicio=data_inicio, data_fim=data_fim)
    sufixo_periodo = ""
    if data_inicio or data_fim:
        sufixo_periodo = f"-{data_inicio or 'inicio'}_a_{data_fim or 'hoje'}"
    filename = f"fiado-{nome}{sufixo_periodo}-{date.today().isoformat()}.pdf".replace(" ", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/sync")
async def sync_fiado(
    current_user: Usuario = Depends(get_current_user),
):
    """Sincroniza o fiado sob demanda: login no iFruti, exporta TODAS as
    vendas em aberto (filtro "situacao=Em Aberto", sem janela de datas) e
    reconcilia com vendas_historico — quem sumiu da lista foi pago.
    """
    _exigir_admin(current_user)

    msg_queue, messages, iniciado_em, put = build_sse_runner()

    def run_scraper():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _run():
            scraper = None
            try:
                put("Exportando vendas em aberto (todas as datas)...")
                async with IFrutiScraper(debug=True) as scraper:
                    put("Login no iFruti...")
                    raw = await scraper.exportar_vendas_em_aberto()

                put("Arquivo exportado, processando...")
                rows = parse_ifruti_xls(raw)

                from database import SessionLocal
                sync_db = SessionLocal()
                try:
                    novos, atualizados, quitados = reconciliar_fiado(sync_db, rows)
                finally:
                    sync_db.close()

                put(
                    f"✓ {len(rows)} linha(s) em aberto no iFruti: {novos} nova(s), "
                    f"{atualizados} atualizada(s), {quitados} quitada(s)"
                )
            except Exception as e:
                put(f"ERRO: {e}")
                if scraper is not None and scraper.page_logs:
                    put("--- diagnóstico (últimas requisições/console) ---")
                    for linha in scraper.page_logs[-20:]:
                        put(linha)
            finally:
                msg_queue.put(None)

        loop.run_until_complete(_run())
        loop.close()
        salvar_no_banco(messages, iniciado_em, "fiado_sync")

    threading.Thread(target=run_scraper, daemon=True).start()

    return StreamingResponse(
        make_stream(msg_queue),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/sync/ultimo-log")
def get_ultimo_log_sync(
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    importacao = (
        db.query(Importacao)
        .filter(Importacao.tipo == "fiado_sync")
        .order_by(Importacao.id.desc())
        .first()
    )
    if not importacao:
        return {"log": None}
    return importacao_to_dict(importacao)
