import asyncio
import threading
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import case, distinct, func
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models.compra_historico import CompraHistorico
from models.importacao import Importacao
from models.usuario import Role, Usuario
from services.compras_import import upsert_compras_rows
from services.compras_parser import parse_compras_xls
from services.compras_reconcile import reconciliar_compras_aberto
from services.scraping import IFrutiScraper
from services.sse_log import build_sse_runner, importacao_to_dict, make_stream, salvar_no_banco

router = APIRouter()

JANELA_SYNC_PADRAO_DIAS = 45

MES_PT = {
    1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
}


def _f(v) -> float:
    return round(float(v or 0), 2)


def _exigir_admin(current_user: Usuario):
    if current_user.role != Role.admin:
        raise HTTPException(403, "Acesso restrito a administradores")


def _filtrar(query, data_inicio, data_fim, fornecedor, produto, status=None):
    if data_inicio:
        query = query.filter(CompraHistorico.data_compra >= data_inicio)
    if data_fim:
        query = query.filter(CompraHistorico.data_compra <= data_fim)
    if fornecedor:
        query = query.filter(CompraHistorico.fornecedor == fornecedor)
    if produto:
        query = query.filter(CompraHistorico.produto == produto)
    if status == "aberto":
        query = query.filter(CompraHistorico.valor_aberto > 0)
    elif status == "pago":
        query = query.filter(CompraHistorico.valor_aberto <= 0)
    return query


# ── Pydantic ─────────────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    importados: int
    atualizados: int
    total: int


class ResumoCompras(BaseModel):
    total_valor: float
    total_pago: float
    total_aberto: float
    pct_aberto: float
    total_linhas: int
    periodo_inicio: Optional[str] = None
    periodo_fim: Optional[str] = None


class MesCompra(BaseModel):
    mes: str
    mes_label: str
    total: float
    count: int


class ItemMixCompras(BaseModel):
    nome: str
    total: float
    count: int
    pct: float


class CompraItem(BaseModel):
    id: int
    data_compra: str
    produto: str
    fornecedor: str
    qtde: int
    valor_unitario: float
    valor_total: float
    valor_aberto: float
    data_pagamento: Optional[str] = None


class OpcoesFiltro(BaseModel):
    fornecedores: list[str]
    produtos: list[str]
    data_inicio: Optional[str] = None
    data_fim: Optional[str] = None


class FaixaAging(BaseModel):
    label: str
    valor: float
    count: int


class AgingResponse(BaseModel):
    total_aberto: float
    faixas: list[FaixaAging]


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/upload", response_model=UploadResponse)
async def upload_compras(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    _exigir_admin(current_user)

    raw = await file.read()
    try:
        rows = parse_compras_xls(raw)
    except Exception as e:
        raise HTTPException(422, f"Erro ao parsear arquivo: {e}")

    importados, atualizados = upsert_compras_rows(db, rows)
    return UploadResponse(
        importados=importados, atualizados=atualizados, total=importados + atualizados
    )


@router.post("/sync")
async def sync_compras(
    current_user: Usuario = Depends(get_current_user),
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
):
    """Sincroniza compras_historico sob demanda: login no iFruti, exporta o
    período (Mercadorias > Compras) e faz upsert, depois reconcilia com o
    snapshot "em aberto" (sem filtro de data) — mesmo padrão de
    routers/despesas.py:sync_despesas.
    """
    _exigir_admin(current_user)

    hoje = date.today()
    inicio = data_inicio or (hoje - timedelta(days=JANELA_SYNC_PADRAO_DIAS))
    fim = data_fim or hoje

    msg_queue, messages, iniciado_em, put = build_sse_runner()

    def run_scraper():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _run():
            scraper = None
            try:
                put(f"Exportando compras de {inicio.strftime('%d/%m/%Y')} até {fim.strftime('%d/%m/%Y')}...")
                async with IFrutiScraper(debug=True) as scraper:
                    put("Login no iFruti...")
                    raw_periodo = await scraper.exportar_compras_periodo(
                        inicio.strftime("%d/%m/%Y"), fim.strftime("%d/%m/%Y")
                    )
                    put("Verificando compras em aberto...")
                    raw_aberto = await scraper.exportar_compras_em_aberto()

                from database import SessionLocal
                sync_db = SessionLocal()
                try:
                    rows_periodo = parse_compras_xls(raw_periodo)
                    if rows_periodo:
                        importados, atualizados = upsert_compras_rows(sync_db, rows_periodo)
                        put(f"✓ {len(rows_periodo)} linha(s) do período: {importados} nova(s), {atualizados} atualizada(s)")
                    else:
                        put(f"Nenhuma compra encontrada no período ({len(raw_periodo)} bytes na resposta)")

                    rows_aberto = parse_compras_xls(raw_aberto)
                    _, _, quitados = reconciliar_compras_aberto(sync_db, rows_aberto)
                    put(f"✓ {len(rows_aberto)} compra(s) em aberto no iFruti — {quitados} quitada(s) desde a última sincronização")
                finally:
                    sync_db.close()
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
        salvar_no_banco(messages, iniciado_em, "compras_sync")

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
        .filter(Importacao.tipo == "compras_sync")
        .order_by(Importacao.id.desc())
        .first()
    )
    if not importacao:
        return {"log": None}
    return importacao_to_dict(importacao)


@router.get("/opcoes-filtro", response_model=OpcoesFiltro)
def get_opcoes_filtro(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    _exigir_admin(current_user)
    fornecedores = [
        r[0] for r in
        db.query(distinct(CompraHistorico.fornecedor)).order_by(CompraHistorico.fornecedor).all()
        if r[0]
    ]
    produtos = [
        r[0] for r in
        db.query(distinct(CompraHistorico.produto)).order_by(CompraHistorico.produto).all()
        if r[0]
    ]
    inicio = db.query(func.min(CompraHistorico.data_compra)).scalar()
    fim = db.query(func.max(CompraHistorico.data_compra)).scalar()
    return OpcoesFiltro(
        fornecedores=fornecedores,
        produtos=produtos,
        data_inicio=inicio.isoformat() if inicio else None,
        data_fim=fim.isoformat() if fim else None,
    )


@router.get("/resumo", response_model=ResumoCompras)
def get_resumo(
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    fornecedor: Optional[str] = Query(default=None),
    produto: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    _exigir_admin(current_user)
    q = db.query(
        func.sum(CompraHistorico.valor_total).label("total"),
        func.sum(CompraHistorico.valor_aberto).label("aberto"),
        func.count(CompraHistorico.id).label("linhas"),
        func.min(CompraHistorico.data_compra).label("inicio"),
        func.max(CompraHistorico.data_compra).label("fim"),
    )
    q = _filtrar(q, data_inicio, data_fim, fornecedor, produto, status)
    row = q.first()

    total = _f(row.total)
    aberto = _f(row.aberto)
    pago = total - aberto
    pct = round((aberto / total * 100) if total > 0 else 0, 1)

    return ResumoCompras(
        total_valor=total,
        total_pago=pago,
        total_aberto=aberto,
        pct_aberto=pct,
        total_linhas=row.linhas or 0,
        periodo_inicio=row.inicio.isoformat() if row.inicio else None,
        periodo_fim=row.fim.isoformat() if row.fim else None,
    )


@router.get("/mensal", response_model=list[MesCompra])
def get_compras_mensal(
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    fornecedor: Optional[str] = Query(default=None),
    produto: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    _exigir_admin(current_user)
    mes_trunc = func.date_trunc("month", CompraHistorico.data_compra)
    q = db.query(
        mes_trunc.label("mes_inicio"),
        func.sum(CompraHistorico.valor_total).label("total"),
        func.count(CompraHistorico.id).label("count"),
    )
    q = _filtrar(q, data_inicio, data_fim, fornecedor, produto, status)
    rows = q.group_by(mes_trunc).order_by(mes_trunc).all()

    result = []
    for r in rows:
        d = r.mes_inicio.date() if hasattr(r.mes_inicio, "date") else r.mes_inicio
        result.append(
            MesCompra(
                mes=d.strftime("%Y-%m"),
                mes_label=f"{MES_PT[d.month]}/{str(d.year)[2:]}",
                total=_f(r.total),
                count=r.count or 0,
            )
        )
    return result


@router.get("/por-fornecedor", response_model=list[ItemMixCompras])
def get_compras_por_fornecedor(
    limit: int = 20,
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    fornecedor: Optional[str] = Query(default=None),
    produto: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    _exigir_admin(current_user)
    q_total = db.query(func.sum(CompraHistorico.valor_total))
    q_total = _filtrar(q_total, data_inicio, data_fim, fornecedor, produto, status)
    total_geral = _f(q_total.scalar())

    q = db.query(
        CompraHistorico.fornecedor,
        func.sum(CompraHistorico.valor_total).label("total"),
        func.count(CompraHistorico.id).label("count"),
    )
    q = _filtrar(q, data_inicio, data_fim, fornecedor, produto, status)
    rows = (
        q.group_by(CompraHistorico.fornecedor)
        .order_by(func.sum(CompraHistorico.valor_total).desc())
        .limit(limit)
        .all()
    )
    return [
        ItemMixCompras(
            nome=r.fornecedor,
            total=_f(r.total),
            count=r.count or 0,
            pct=round(_f(r.total) / total_geral * 100 if total_geral else 0, 1),
        )
        for r in rows
    ]


@router.get("/por-produto", response_model=list[ItemMixCompras])
def get_compras_por_produto(
    limit: int = 20,
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    fornecedor: Optional[str] = Query(default=None),
    produto: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    _exigir_admin(current_user)
    q_total = db.query(func.sum(CompraHistorico.valor_total))
    q_total = _filtrar(q_total, data_inicio, data_fim, fornecedor, produto, status)
    total_geral = _f(q_total.scalar())

    q = db.query(
        CompraHistorico.produto,
        func.sum(CompraHistorico.valor_total).label("total"),
        func.count(CompraHistorico.id).label("count"),
    )
    q = _filtrar(q, data_inicio, data_fim, fornecedor, produto, status)
    rows = (
        q.group_by(CompraHistorico.produto)
        .order_by(func.sum(CompraHistorico.valor_total).desc())
        .limit(limit)
        .all()
    )
    return [
        ItemMixCompras(
            nome=r.produto,
            total=_f(r.total),
            count=r.count or 0,
            pct=round(_f(r.total) / total_geral * 100 if total_geral else 0, 1),
        )
        for r in rows
    ]


@router.get("/aging", response_model=AgingResponse)
def get_compras_aging(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Compras em aberto agrupadas por tempo desde a compra — essa tela não
    expõe data de vencimento (diferente de Despesas), então o aging aqui é
    por dias já em aberto, mesmo espírito do aging de contas a receber em
    routers/fiado.py.
    """
    _exigir_admin(current_user)

    dias_aberto = func.current_date() - CompraHistorico.data_compra
    aging_faixa = case(
        (dias_aberto <= 7, "Até 7 dias"),
        (dias_aberto <= 30, "8–30 dias"),
        else_="+30 dias",
    )

    rows_aging = (
        db.query(
            aging_faixa.label("faixa"),
            func.sum(CompraHistorico.valor_aberto).label("valor"),
            func.count(CompraHistorico.id).label("cnt"),
        )
        .filter(CompraHistorico.valor_aberto > 0)
        .group_by(aging_faixa)
        .all()
    )
    ordem = {"Até 7 dias": 0, "8–30 dias": 1, "+30 dias": 2}
    faixas = [
        FaixaAging(label=r.faixa, valor=_f(r.valor), count=r.cnt or 0)
        for r in sorted(rows_aging, key=lambda x: ordem.get(x.faixa, 99))
    ]
    total_aberto = round(sum(f.valor for f in faixas), 2)

    return AgingResponse(total_aberto=total_aberto, faixas=faixas)


@router.get("", response_model=list[CompraItem])
def list_compras(
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    fornecedor: Optional[str] = Query(default=None),
    produto: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = 500,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    _exigir_admin(current_user)
    q = db.query(CompraHistorico)
    q = _filtrar(q, data_inicio, data_fim, fornecedor, produto, status)
    rows = (
        q.order_by(CompraHistorico.data_compra.desc(), CompraHistorico.id.desc())
        .limit(limit)
        .all()
    )
    return [
        CompraItem(
            id=r.id,
            data_compra=r.data_compra.isoformat(),
            produto=r.produto,
            fornecedor=r.fornecedor,
            qtde=r.qtde,
            valor_unitario=_f(r.valor_unitario),
            valor_total=_f(r.valor_total),
            valor_aberto=_f(r.valor_aberto),
            data_pagamento=r.data_pagamento.isoformat() if r.data_pagamento else None,
        )
        for r in rows
    ]
