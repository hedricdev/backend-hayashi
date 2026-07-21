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
from models.despesa_historico import DespesaHistorico
from models.importacao import Importacao
from models.usuario import Role, Usuario
from services.despesas_import import upsert_despesas_rows
from services.despesas_parser import parse_despesas_xls
from services.despesas_reconcile import reconciliar_despesas_aberto
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


def _filtrar(query, data_inicio, data_fim, credor, descricao, status=None):
    if data_inicio:
        query = query.filter(DespesaHistorico.data_despesa >= data_inicio)
    if data_fim:
        query = query.filter(DespesaHistorico.data_despesa <= data_fim)
    if credor:
        query = query.filter(DespesaHistorico.credor == credor)
    if descricao:
        query = query.filter(DespesaHistorico.descricao == descricao)
    if status == "aberto":
        query = query.filter(DespesaHistorico.valor_aberto > 0)
    elif status == "pago":
        query = query.filter(DespesaHistorico.valor_aberto <= 0)
    return query


# ── Pydantic ─────────────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    importados: int
    atualizados: int
    total: int


class ResumoDespesas(BaseModel):
    total_valor: float
    total_pago: float
    total_aberto: float
    pct_aberto: float
    total_linhas: int
    periodo_inicio: Optional[str] = None
    periodo_fim: Optional[str] = None


class MesDespesa(BaseModel):
    mes: str
    mes_label: str
    total: float
    count: int


class CategoriaDespesa(BaseModel):
    nome: str
    total: float
    count: int
    pct: float


class DespesaItem(BaseModel):
    id: int
    data_despesa: str
    descricao: str
    loja: str
    credor: str
    data_vencimento: Optional[str] = None
    valor: float
    valor_aberto: float
    data_pagamento: Optional[str] = None


class OpcoesFiltro(BaseModel):
    credores: list[str]
    descricoes: list[str]
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
async def upload_despesas(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    _exigir_admin(current_user)

    raw = await file.read()
    try:
        rows = parse_despesas_xls(raw)
    except Exception as e:
        raise HTTPException(422, f"Erro ao parsear arquivo: {e}")

    importados, atualizados = upsert_despesas_rows(db, rows)
    return UploadResponse(
        importados=importados, atualizados=atualizados, total=importados + atualizados
    )


@router.post("/sync")
async def sync_despesas(
    current_user: Usuario = Depends(get_current_user),
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
):
    """Sincroniza despesas_historico sob demanda: login no iFruti, exporta o
    período (Financeiro > Despesas > Exportar Excel) e faz upsert.

    Sem datas explícitas, usa uma janela móvel dos últimos 45 dias — mesmo
    racional de historico.sync_historico: margem segura pra capturar despesas
    que foram pagas depois do lançamento original, sem reexportar tudo a cada
    sincronização.
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
                put(f"Exportando despesas de {inicio.strftime('%d/%m/%Y')} até {fim.strftime('%d/%m/%Y')}...")
                async with IFrutiScraper(debug=True) as scraper:
                    put("Login no iFruti...")
                    raw_periodo = await scraper.exportar_despesas_periodo(
                        inicio.strftime("%d/%m/%Y"), fim.strftime("%d/%m/%Y")
                    )
                    put("Verificando despesas em aberto...")
                    raw_aberto = await scraper.exportar_despesas_em_aberto()

                from database import SessionLocal
                sync_db = SessionLocal()
                try:
                    rows_periodo = parse_despesas_xls(raw_periodo)
                    if rows_periodo:
                        importados, atualizados = upsert_despesas_rows(sync_db, rows_periodo)
                        put(f"✓ {len(rows_periodo)} linha(s) do período: {importados} nova(s), {atualizados} atualizada(s)")
                    else:
                        put(f"Nenhuma despesa encontrada no período ({len(raw_periodo)} bytes na resposta)")

                    rows_aberto = parse_despesas_xls(raw_aberto)
                    _, _, quitados = reconciliar_despesas_aberto(sync_db, rows_aberto)
                    put(f"✓ {len(rows_aberto)} despesa(s) em aberto no iFruti — {quitados} quitada(s) desde a última sincronização")
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
        salvar_no_banco(messages, iniciado_em, "despesas_sync")

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
        .filter(Importacao.tipo == "despesas_sync")
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
    credores = [
        r[0] for r in
        db.query(distinct(DespesaHistorico.credor)).order_by(DespesaHistorico.credor).all()
        if r[0]
    ]
    descricoes = [
        r[0] for r in
        db.query(distinct(DespesaHistorico.descricao)).order_by(DespesaHistorico.descricao).all()
        if r[0]
    ]
    inicio = db.query(func.min(DespesaHistorico.data_despesa)).scalar()
    fim = db.query(func.max(DespesaHistorico.data_despesa)).scalar()
    return OpcoesFiltro(
        credores=credores,
        descricoes=descricoes,
        data_inicio=inicio.isoformat() if inicio else None,
        data_fim=fim.isoformat() if fim else None,
    )


@router.get("/resumo", response_model=ResumoDespesas)
def get_resumo(
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    credor: Optional[str] = Query(default=None),
    descricao: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    _exigir_admin(current_user)
    q = db.query(
        func.sum(DespesaHistorico.valor).label("total"),
        func.sum(DespesaHistorico.valor_aberto).label("aberto"),
        func.count(DespesaHistorico.id).label("linhas"),
        func.min(DespesaHistorico.data_despesa).label("inicio"),
        func.max(DespesaHistorico.data_despesa).label("fim"),
    )
    q = _filtrar(q, data_inicio, data_fim, credor, descricao, status)
    row = q.first()

    total = _f(row.total)
    aberto = _f(row.aberto)
    pago = total - aberto
    pct = round((aberto / total * 100) if total > 0 else 0, 1)

    return ResumoDespesas(
        total_valor=total,
        total_pago=pago,
        total_aberto=aberto,
        pct_aberto=pct,
        total_linhas=row.linhas or 0,
        periodo_inicio=row.inicio.isoformat() if row.inicio else None,
        periodo_fim=row.fim.isoformat() if row.fim else None,
    )


@router.get("/mensal", response_model=list[MesDespesa])
def get_despesas_mensal(
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    credor: Optional[str] = Query(default=None),
    descricao: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    _exigir_admin(current_user)
    mes_trunc = func.date_trunc("month", DespesaHistorico.data_despesa)
    q = db.query(
        mes_trunc.label("mes_inicio"),
        func.sum(DespesaHistorico.valor).label("total"),
        func.count(DespesaHistorico.id).label("count"),
    )
    q = _filtrar(q, data_inicio, data_fim, credor, descricao, status)
    rows = q.group_by(mes_trunc).order_by(mes_trunc).all()

    result = []
    for r in rows:
        d = r.mes_inicio.date() if hasattr(r.mes_inicio, "date") else r.mes_inicio
        result.append(
            MesDespesa(
                mes=d.strftime("%Y-%m"),
                mes_label=f"{MES_PT[d.month]}/{str(d.year)[2:]}",
                total=_f(r.total),
                count=r.count or 0,
            )
        )
    return result


@router.get("/por-categoria", response_model=list[CategoriaDespesa])
def get_despesas_por_categoria(
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    credor: Optional[str] = Query(default=None),
    descricao: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    _exigir_admin(current_user)
    q_total = db.query(func.sum(DespesaHistorico.valor))
    q_total = _filtrar(q_total, data_inicio, data_fim, credor, descricao, status)
    total_geral = _f(q_total.scalar())

    q = db.query(
        DespesaHistorico.descricao,
        func.sum(DespesaHistorico.valor).label("total"),
        func.count(DespesaHistorico.id).label("count"),
    )
    q = _filtrar(q, data_inicio, data_fim, credor, descricao, status)
    rows = (
        q.group_by(DespesaHistorico.descricao)
        .order_by(func.sum(DespesaHistorico.valor).desc())
        .all()
    )
    return [
        CategoriaDespesa(
            nome=r.descricao,
            total=_f(r.total),
            count=r.count or 0,
            pct=round(_f(r.total) / total_geral * 100 if total_geral else 0, 1),
        )
        for r in rows
    ]


@router.get("/por-credor", response_model=list[CategoriaDespesa])
def get_despesas_por_credor(
    limit: int = 20,
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    credor: Optional[str] = Query(default=None),
    descricao: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    _exigir_admin(current_user)
    q_total = db.query(func.sum(DespesaHistorico.valor))
    q_total = _filtrar(q_total, data_inicio, data_fim, credor, descricao, status)
    total_geral = _f(q_total.scalar())

    q = db.query(
        DespesaHistorico.credor,
        func.sum(DespesaHistorico.valor).label("total"),
        func.count(DespesaHistorico.id).label("count"),
    )
    q = _filtrar(q, data_inicio, data_fim, credor, descricao, status)
    rows = (
        q.group_by(DespesaHistorico.credor)
        .order_by(func.sum(DespesaHistorico.valor).desc())
        .limit(limit)
        .all()
    )
    return [
        CategoriaDespesa(
            nome=r.credor,
            total=_f(r.total),
            count=r.count or 0,
            pct=round(_f(r.total) / total_geral * 100 if total_geral else 0, 1),
        )
        for r in rows
    ]


@router.get("/aging", response_model=AgingResponse)
def get_despesas_aging(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Despesas em aberto agrupadas por proximidade do vencimento — mesmo
    espírito do aging de contas a receber em routers/fiado.py, só que
    olhando pra frente (dias até vencer) em vez de atraso.
    """
    _exigir_admin(current_user)

    dias_para_vencer = DespesaHistorico.data_vencimento - func.current_date()
    aging_faixa = case(
        (dias_para_vencer < 0, "Vencido"),
        (dias_para_vencer <= 7, "Vence em até 7 dias"),
        (dias_para_vencer <= 30, "Vence em 8–30 dias"),
        else_="Vence em +30 dias",
    )

    rows_aging = (
        db.query(
            aging_faixa.label("faixa"),
            func.sum(DespesaHistorico.valor_aberto).label("valor"),
            func.count(DespesaHistorico.id).label("cnt"),
        )
        .filter(
            DespesaHistorico.valor_aberto > 0,
            DespesaHistorico.data_vencimento.isnot(None),
        )
        .group_by(aging_faixa)
        .all()
    )
    ordem = {
        "Vencido": 0, "Vence em até 7 dias": 1,
        "Vence em 8–30 dias": 2, "Vence em +30 dias": 3,
    }
    faixas = [
        FaixaAging(label=r.faixa, valor=_f(r.valor), count=r.cnt or 0)
        for r in sorted(rows_aging, key=lambda x: ordem.get(x.faixa, 99))
    ]
    total_aberto = round(sum(f.valor for f in faixas), 2)

    return AgingResponse(total_aberto=total_aberto, faixas=faixas)


@router.get("", response_model=list[DespesaItem])
def list_despesas(
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    credor: Optional[str] = Query(default=None),
    descricao: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = 500,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    _exigir_admin(current_user)
    q = db.query(DespesaHistorico)
    q = _filtrar(q, data_inicio, data_fim, credor, descricao, status)
    rows = (
        q.order_by(DespesaHistorico.data_despesa.desc(), DespesaHistorico.id.desc())
        .limit(limit)
        .all()
    )
    return [
        DespesaItem(
            id=r.id,
            data_despesa=r.data_despesa.isoformat(),
            descricao=r.descricao,
            loja=r.loja,
            credor=r.credor,
            data_vencimento=r.data_vencimento.isoformat() if r.data_vencimento else None,
            valor=_f(r.valor),
            valor_aberto=_f(r.valor_aberto),
            data_pagamento=r.data_pagamento.isoformat() if r.data_pagamento else None,
        )
        for r in rows
    ]
