import asyncio
import logging
import threading
import time
from datetime import date, datetime, timedelta

from config import settings
from database import SessionLocal
from services.compras_import import upsert_compras_rows
from services.compras_parser import parse_compras_xls
from services.compras_reconcile import reconciliar_compras_aberto
from services.despesas_import import upsert_despesas_rows
from services.despesas_parser import parse_despesas_xls
from services.despesas_reconcile import reconciliar_despesas_aberto
from services.fiado_reconcile import reconciliar_fiado
from services.historico_import import upsert_historico_rows
from services.historico_parser import parse_ifruti_xls
from services.scraping import IFrutiScraper
from services.sse_log import salvar_no_banco

logger = logging.getLogger("auto_sync")

JANELA_SYNC_PADRAO_DIAS = 45


async def _sync_vendas_historico() -> list[str]:
    hoje = date.today()
    inicio = hoje - timedelta(days=JANELA_SYNC_PADRAO_DIAS)
    async with IFrutiScraper(debug=True) as scraper:
        raw = await scraper.exportar_vendas_periodo(
            inicio.strftime("%d/%m/%Y"), hoje.strftime("%d/%m/%Y")
        )
    rows = parse_ifruti_xls(raw)
    if not rows:
        return [f"Nenhuma venda encontrada no período ({len(raw)} bytes na resposta)"]
    db = SessionLocal()
    try:
        importados, atualizados = upsert_historico_rows(db, rows)
    finally:
        db.close()
    return [f"✓ Vendas: {len(rows)} linha(s) — {importados} nova(s), {atualizados} atualizada(s)"]


async def _sync_fiado() -> list[str]:
    async with IFrutiScraper(debug=True) as scraper:
        raw = await scraper.exportar_vendas_em_aberto()
    rows = parse_ifruti_xls(raw)
    db = SessionLocal()
    try:
        novos, atualizados, quitados = reconciliar_fiado(db, rows)
    finally:
        db.close()
    return [
        f"✓ Fiado: {len(rows)} em aberto — {novos} nova(s), {atualizados} atualizada(s), "
        f"{quitados} quitada(s)"
    ]


async def _sync_despesas() -> list[str]:
    hoje = date.today()
    inicio = hoje - timedelta(days=JANELA_SYNC_PADRAO_DIAS)
    msgs: list[str] = []
    async with IFrutiScraper(debug=True) as scraper:
        raw_periodo = await scraper.exportar_despesas_periodo(
            inicio.strftime("%d/%m/%Y"), hoje.strftime("%d/%m/%Y")
        )
        raw_aberto = await scraper.exportar_despesas_em_aberto()

    db = SessionLocal()
    try:
        rows_periodo = parse_despesas_xls(raw_periodo)
        if rows_periodo:
            importados, atualizados = upsert_despesas_rows(db, rows_periodo)
            msgs.append(
                f"✓ Despesas: {len(rows_periodo)} linha(s) do período — {importados} nova(s), "
                f"{atualizados} atualizada(s)"
            )
        else:
            msgs.append(f"Nenhuma despesa encontrada no período ({len(raw_periodo)} bytes na resposta)")

        rows_aberto = parse_despesas_xls(raw_aberto)
        _, _, quitados = reconciliar_despesas_aberto(db, rows_aberto)
        msgs.append(f"✓ Despesas em aberto: {len(rows_aberto)} — {quitados} quitada(s)")
    finally:
        db.close()
    return msgs


async def _sync_compras() -> list[str]:
    hoje = date.today()
    inicio = hoje - timedelta(days=JANELA_SYNC_PADRAO_DIAS)
    msgs: list[str] = []
    async with IFrutiScraper(debug=True) as scraper:
        raw_periodo = await scraper.exportar_compras_periodo(
            inicio.strftime("%d/%m/%Y"), hoje.strftime("%d/%m/%Y")
        )
        raw_aberto = await scraper.exportar_compras_em_aberto()

    db = SessionLocal()
    try:
        rows_periodo = parse_compras_xls(raw_periodo)
        if rows_periodo:
            importados, atualizados = upsert_compras_rows(db, rows_periodo)
            msgs.append(
                f"✓ Compras: {len(rows_periodo)} linha(s) do período — {importados} nova(s), "
                f"{atualizados} atualizada(s)"
            )
        else:
            msgs.append(f"Nenhuma compra encontrada no período ({len(raw_periodo)} bytes na resposta)")

        rows_aberto = parse_compras_xls(raw_aberto)
        _, _, quitados = reconciliar_compras_aberto(db, rows_aberto)
        msgs.append(f"✓ Compras em aberto: {len(rows_aberto)} — {quitados} quitada(s)")
    finally:
        db.close()
    return msgs


# Mesmos valores de `tipo` usados pelos endpoints /sync manuais — o painel
# "Último sync" de cada tela não distingue quem disparou, só o resultado mais
# recente, então uma execução automática já aparece lá naturalmente.
_FLUXOS = [
    ("Vendas/Histórico", "historico_sync", _sync_vendas_historico),
    ("Fiado", "fiado_sync", _sync_fiado),
    ("Despesas", "despesas_sync", _sync_despesas),
    ("Compras", "compras_sync", _sync_compras),
]


async def _executar_um(nome: str, tipo: str, fn, put=None) -> None:
    iniciado_em = datetime.utcnow()
    if put:
        put(f"Sincronizando {nome}...")
    try:
        msgs = await fn()
        salvar_no_banco(msgs, iniciado_em, tipo)
        logger.info("[auto-sync] %s: ok — %s", nome, "; ".join(msgs))
        if put:
            for m in msgs:
                put(m)
    except Exception as e:
        salvar_no_banco([f"ERRO: {e}"], iniciado_em, tipo)
        logger.exception("[auto-sync] %s: falhou", nome)
        if put:
            put(f"ERRO em {nome}: {e}")


async def executar_sync_completo(put=None) -> None:
    """Roda os 4 fluxos de sincronização em sequência (uma sessão de login
    por fluxo, na ordem que já é usada nas telas manuais). Erros em um fluxo
    não impedem os seguintes — cada um salva seu próprio log em `importacoes`.

    `put`, se passado, recebe mensagens de progresso em tempo real (usado
    pelo endpoint `/sync/completo` sob demanda); o job automático de 1h
    roda sem `put`, só logando via `logger`.
    """
    for nome, tipo, fn in _FLUXOS:
        await _executar_um(nome, tipo, fn, put=put)


def iniciar_loop_background() -> None:
    """Dispara uma thread daemon que roda `executar_sync_completo` assim que
    o servidor sobe, e depois a cada `AUTO_SYNC_INTERVALO_SEGUNDOS` (padrão
    1h). Fica de fora do event loop principal do FastAPI porque cada fluxo já
    abre sua própria sessão Playwright (mesmo padrão dos endpoints /sync).
    """

    def _worker():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while True:
            try:
                loop.run_until_complete(executar_sync_completo())
            except Exception:
                logger.exception("[auto-sync] ciclo completo falhou")
            time.sleep(settings.AUTO_SYNC_INTERVALO_SEGUNDOS)

    threading.Thread(target=_worker, daemon=True).start()
