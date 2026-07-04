import asyncio
import threading
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import case, distinct, func
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models.importacao import Importacao
from models.usuario import Role, Usuario
from models.venda_historico import VendaHistorico
from services.historico_import import upsert_historico_rows
from services.historico_parser import parse_ifruti_xls
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


def _filtrar(query, data_inicio, data_fim, cliente, produto, fornecedor):
    if data_inicio:
        query = query.filter(VendaHistorico.data >= data_inicio)
    if data_fim:
        query = query.filter(VendaHistorico.data <= data_fim)
    if cliente:
        query = query.filter(VendaHistorico.cliente == cliente)
    if produto:
        query = query.filter(VendaHistorico.produto == produto)
    if fornecedor:
        query = query.filter(VendaHistorico.fornecedor == fornecedor)
    return query


# ── Pydantic models ──────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    importados: int
    atualizados: int
    total: int


class ResumoHistorico(BaseModel):
    total_faturamento: float
    total_recebido: float
    total_aberto: float
    pct_inadimplencia: float
    total_clientes: int
    total_caixas: int
    total_linhas: int
    periodo_inicio: Optional[str] = None
    periodo_fim: Optional[str] = None


class MesFaturamento(BaseModel):
    mes: str
    mes_label: str
    faturamento: float
    recebido: float
    aberto: float
    caixas: int
    clientes: int


class ClienteMetrica(BaseModel):
    nome: str
    faturamento: float
    recebido: float
    aberto: float
    caixas: int
    dias_compra: int
    pct_inadimplencia: float


class FaixaAging(BaseModel):
    label: str
    valor: float
    count: int


class InadimplenciaResponse(BaseModel):
    total_aberto: float
    faixas: list[FaixaAging]
    top_devedores: list[ClienteMetrica]


class ItemMix(BaseModel):
    nome: str
    faturamento: float
    caixas: int
    pct: float


class MixProdutosResponse(BaseModel):
    por_categoria: list[ItemMix]
    por_fornecedor: list[ItemMix]
    por_produto: list[ItemMix]


class OpcoesFiltro(BaseModel):
    clientes: list[str]
    produtos: list[str]
    fornecedores: list[str]
    data_inicio: Optional[str] = None
    data_fim: Optional[str] = None


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/upload", response_model=UploadResponse)
async def upload_historico(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    if current_user.role != Role.admin:
        raise HTTPException(403, "Apenas admin pode importar histórico")

    raw = await file.read()
    try:
        rows = parse_ifruti_xls(raw)
    except Exception as e:
        raise HTTPException(422, f"Erro ao parsear arquivo: {e}")

    importados, atualizados = upsert_historico_rows(db, rows)
    return UploadResponse(
        importados=importados, atualizados=atualizados, total=importados + atualizados
    )


@router.post("/sync")
async def sync_historico(
    current_user: Usuario = Depends(get_current_user),
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
):
    """Sincroniza vendas_historico sob demanda: login no iFruti, exporta o
    período (Mercadorias > Distribuidora > Exportar Excel) e faz upsert.

    Sem datas explícitas, usa uma janela móvel dos últimos 45 dias — margem
    segura para capturar fiado que foi pago depois do lançamento original,
    sem reexportar o histórico inteiro a cada sincronização.
    """
    if current_user.role != Role.admin:
        raise HTTPException(403, "Apenas admin pode sincronizar histórico")

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
                put(f"Exportando vendas de {inicio.strftime('%d/%m/%Y')} até {fim.strftime('%d/%m/%Y')}...")
                async with IFrutiScraper(debug=True) as scraper:
                    put("Login no iFruti...")
                    raw = await scraper.exportar_vendas_periodo(
                        inicio.strftime("%d/%m/%Y"), fim.strftime("%d/%m/%Y")
                    )

                put("Arquivo exportado, processando...")
                rows = parse_ifruti_xls(raw)
                if not rows:
                    trecho = raw.decode("utf-8", errors="ignore")[:800].replace("\n", " ").strip()
                    put(f"Nenhuma linha encontrada no período (resposta teve {len(raw)} bytes)")
                    put(f"--- trecho da resposta recebida --- {trecho}")
                    return

                from database import SessionLocal
                sync_db = SessionLocal()
                try:
                    importados, atualizados = upsert_historico_rows(sync_db, rows)
                finally:
                    sync_db.close()

                put(f"✓ {len(rows)} linha(s) processada(s): {importados} nova(s), {atualizados} atualizada(s)")
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
        salvar_no_banco(messages, iniciado_em, "historico_sync")

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
        .filter(Importacao.tipo == "historico_sync")
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
    clientes = [
        r[0] for r in
        db.query(distinct(VendaHistorico.cliente)).order_by(VendaHistorico.cliente).all()
        if r[0]
    ]
    produtos = [
        r[0] for r in
        db.query(distinct(VendaHistorico.produto)).order_by(VendaHistorico.produto).all()
        if r[0]
    ]
    fornecedores = [
        r[0] for r in
        db.query(distinct(VendaHistorico.fornecedor)).order_by(VendaHistorico.fornecedor).all()
        if r[0]
    ]
    inicio = db.query(func.min(VendaHistorico.data)).scalar()
    fim = db.query(func.max(VendaHistorico.data)).scalar()
    return OpcoesFiltro(
        clientes=clientes,
        produtos=produtos,
        fornecedores=fornecedores,
        data_inicio=inicio.isoformat() if inicio else None,
        data_fim=fim.isoformat() if fim else None,
    )


@router.get("/resumo", response_model=ResumoHistorico)
def get_resumo(
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    cliente: Optional[str] = Query(default=None),
    produto: Optional[str] = Query(default=None),
    fornecedor: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    q = db.query(
        func.sum(VendaHistorico.total_item).label("fat"),
        func.sum(VendaHistorico.valor_aberto).label("aberto"),
        func.count(distinct(VendaHistorico.cliente)).label("clientes"),
        func.sum(VendaHistorico.qtde).label("caixas"),
        func.count(VendaHistorico.id).label("linhas"),
        func.min(VendaHistorico.data).label("inicio"),
        func.max(VendaHistorico.data).label("fim"),
    )
    q = _filtrar(q, data_inicio, data_fim, cliente, produto, fornecedor)
    row = q.first()

    fat = _f(row.fat)
    aberto = _f(row.aberto)
    recebido = fat - aberto
    pct = round((aberto / fat * 100) if fat > 0 else 0, 1)

    return ResumoHistorico(
        total_faturamento=fat,
        total_recebido=recebido,
        total_aberto=aberto,
        pct_inadimplencia=pct,
        total_clientes=row.clientes or 0,
        total_caixas=row.caixas or 0,
        total_linhas=row.linhas or 0,
        periodo_inicio=row.inicio.isoformat() if row.inicio else None,
        periodo_fim=row.fim.isoformat() if row.fim else None,
    )


@router.get("/faturamento-mensal", response_model=list[MesFaturamento])
def get_faturamento_mensal(
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    cliente: Optional[str] = Query(default=None),
    produto: Optional[str] = Query(default=None),
    fornecedor: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    mes_trunc = func.date_trunc("month", VendaHistorico.data)
    q = db.query(
        mes_trunc.label("mes_inicio"),
        func.sum(VendaHistorico.total_item).label("fat"),
        func.sum(VendaHistorico.valor_aberto).label("aberto"),
        func.sum(VendaHistorico.qtde).label("caixas"),
        func.count(distinct(VendaHistorico.cliente)).label("clientes"),
    )
    q = _filtrar(q, data_inicio, data_fim, cliente, produto, fornecedor)
    rows = q.group_by(mes_trunc).order_by(mes_trunc).all()

    result = []
    for r in rows:
        d = r.mes_inicio.date() if hasattr(r.mes_inicio, "date") else r.mes_inicio
        fat = _f(r.fat)
        aberto = _f(r.aberto)
        result.append(
            MesFaturamento(
                mes=d.strftime("%Y-%m"),
                mes_label=f"{MES_PT[d.month]}/{str(d.year)[2:]}",
                faturamento=fat,
                recebido=fat - aberto,
                aberto=aberto,
                caixas=r.caixas or 0,
                clientes=r.clientes or 0,
            )
        )
    return result


@router.get("/top-clientes", response_model=list[ClienteMetrica])
def get_top_clientes(
    limit: int = 15,
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    cliente: Optional[str] = Query(default=None),
    produto: Optional[str] = Query(default=None),
    fornecedor: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    q = db.query(
        VendaHistorico.cliente,
        func.sum(VendaHistorico.total_item).label("fat"),
        func.sum(VendaHistorico.valor_aberto).label("aberto"),
        func.sum(VendaHistorico.qtde).label("caixas"),
        func.count(distinct(VendaHistorico.data)).label("dias"),
    )
    q = _filtrar(q, data_inicio, data_fim, cliente, produto, fornecedor)
    rows = (
        q.group_by(VendaHistorico.cliente)
        .order_by(func.sum(VendaHistorico.total_item).desc())
        .limit(limit)
        .all()
    )
    result = []
    for r in rows:
        fat = _f(r.fat)
        aberto = _f(r.aberto)
        pct = round((aberto / fat * 100) if fat > 0 else 0, 1)
        result.append(
            ClienteMetrica(
                nome=r.cliente,
                faturamento=fat,
                recebido=fat - aberto,
                aberto=aberto,
                caixas=r.caixas or 0,
                dias_compra=r.dias or 0,
                pct_inadimplencia=pct,
            )
        )
    return result


@router.get("/inadimplencia", response_model=InadimplenciaResponse)
def get_inadimplencia(
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    cliente: Optional[str] = Query(default=None),
    produto: Optional[str] = Query(default=None),
    fornecedor: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    aging_faixa = case(
        (func.current_date() - VendaHistorico.data <= 7, "Até 7 dias"),
        (func.current_date() - VendaHistorico.data <= 30, "8–30 dias"),
        else_="+30 dias",
    )

    q_aging = db.query(
        aging_faixa.label("faixa"),
        func.sum(VendaHistorico.valor_aberto).label("valor"),
        func.count(VendaHistorico.id).label("cnt"),
    ).filter(VendaHistorico.valor_aberto > 0)
    q_aging = _filtrar(q_aging, data_inicio, data_fim, cliente, produto, fornecedor)
    rows_aging = q_aging.group_by(aging_faixa).all()

    q_total = db.query(func.sum(VendaHistorico.valor_aberto)).filter(VendaHistorico.valor_aberto > 0)
    q_total = _filtrar(q_total, data_inicio, data_fim, cliente, produto, fornecedor)
    total_aberto = _f(q_total.scalar())

    ordem = {"Até 7 dias": 0, "8–30 dias": 1, "+30 dias": 2}
    faixas = [
        FaixaAging(label=r.faixa, valor=_f(r.valor), count=r.cnt or 0)
        for r in sorted(rows_aging, key=lambda x: ordem.get(x.faixa, 99))
    ]

    q_top = db.query(
        VendaHistorico.cliente,
        func.sum(VendaHistorico.total_item).label("fat"),
        func.sum(VendaHistorico.valor_aberto).label("aberto"),
        func.sum(VendaHistorico.qtde).label("caixas"),
        func.count(distinct(VendaHistorico.data)).label("dias"),
    ).filter(VendaHistorico.valor_aberto > 0)
    q_top = _filtrar(q_top, data_inicio, data_fim, cliente, produto, fornecedor)
    top_rows = (
        q_top.group_by(VendaHistorico.cliente)
        .order_by(func.sum(VendaHistorico.valor_aberto).desc())
        .limit(10)
        .all()
    )
    top_devedores = []
    for r in top_rows:
        fat = _f(r.fat)
        aberto = _f(r.aberto)
        pct = round((aberto / fat * 100) if fat > 0 else 0, 1)
        top_devedores.append(
            ClienteMetrica(
                nome=r.cliente,
                faturamento=fat,
                recebido=fat - aberto,
                aberto=aberto,
                caixas=r.caixas or 0,
                dias_compra=r.dias or 0,
                pct_inadimplencia=pct,
            )
        )

    return InadimplenciaResponse(
        total_aberto=total_aberto,
        faixas=faixas,
        top_devedores=top_devedores,
    )


@router.get("/mix-produtos", response_model=MixProdutosResponse)
def get_mix_produtos(
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    cliente: Optional[str] = Query(default=None),
    produto: Optional[str] = Query(default=None),
    fornecedor: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    q_total = db.query(func.sum(VendaHistorico.total_item))
    q_total = _filtrar(q_total, data_inicio, data_fim, cliente, produto, fornecedor)
    total_fat = _f(q_total.scalar())

    def _build(col):
        q = db.query(
            col.label("nome"),
            func.sum(VendaHistorico.total_item).label("fat"),
            func.sum(VendaHistorico.qtde).label("caixas"),
        )
        q = _filtrar(q, data_inicio, data_fim, cliente, produto, fornecedor)
        rows = q.group_by(col).order_by(func.sum(VendaHistorico.total_item).desc()).all()
        return [
            ItemMix(
                nome=r.nome or "Outros",
                faturamento=_f(r.fat),
                caixas=r.caixas or 0,
                pct=round(_f(r.fat) / total_fat * 100 if total_fat else 0, 1),
            )
            for r in rows
        ]

    return MixProdutosResponse(
        por_categoria=_build(VendaHistorico.categoria),
        por_fornecedor=_build(VendaHistorico.fornecedor),
        por_produto=_build(VendaHistorico.produto),
    )


_DIAS_SEMANA = ["SEGUNDA", "TERÇA", "QUARTA", "QUINTA", "SEXTA", "SABADO", "DOMINGO"]


class ProdutoDetalhe(BaseModel):
    nome: str
    quantidade: int


class VendaDetalhe(BaseModel):
    cliente: str
    vendedor: str
    pagamento: str
    preco: str
    produtos: list[ProdutoDetalhe]
    dia: str
    data: Optional[str] = None


class VendasDetalhamentoResponse(BaseModel):
    vendas: list[VendaDetalhe]
    total: int


@router.get("/vendas", response_model=VendasDetalhamentoResponse)
def get_vendas_detalhamento(
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Lista transações individuais do iFruti para o Detalhamento de Vendas.
    Agrupa linhas de produto por (data, cliente) para reconstruir cada venda.
    """
    q = db.query(VendaHistorico)
    if data_inicio:
        q = q.filter(VendaHistorico.data >= data_inicio)
    if data_fim:
        q = q.filter(VendaHistorico.data <= data_fim)

    rows = q.order_by(
        VendaHistorico.data.desc(), VendaHistorico.cliente, VendaHistorico.produto
    ).all()

    groups: dict = defaultdict(list)
    for r in rows:
        groups[(r.data, r.cliente)].append(r)

    vendas: list[VendaDetalhe] = []
    for (data_venda, cliente), g_rows in groups.items():
        aberto = sum(float(r.valor_aberto or 0) for r in g_rows)
        dia_semana = _DIAS_SEMANA[data_venda.weekday()]
        preco_str = "/".join(
            f"{float(r.total_item or 0):.2f}".replace(".", ",") for r in g_rows
        )
        vendas.append(
            VendaDetalhe(
                cliente=cliente,
                vendedor="",
                pagamento="" if aberto > 0 else "RECEBIDO",
                preco=preco_str,
                produtos=[ProdutoDetalhe(nome=r.produto, quantidade=r.qtde) for r in g_rows],
                dia=dia_semana,
                data=str(data_venda),
            )
        )

    # Ordena por data desc (já estava desc na query, mas defaultdict não preserva ordem)
    vendas.sort(key=lambda v: v.data or "", reverse=True)

    return VendasDetalhamentoResponse(vendas=vendas, total=len(vendas))
