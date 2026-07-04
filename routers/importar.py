import asyncio
import threading

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from models.importacao import Importacao
from services.scraping import IFrutiScraper
from services.sheets import get_lista_diaria, get_vendas_nao_importadas, get_aba_atual, get_aba_venda_atual
from services.sse_log import build_sse_runner, importacao_to_dict, make_stream, salvar_no_banco

router = APIRouter()


@router.post("/lista-diaria")
async def importar_lista_diaria():
    msg_queue, messages, iniciado_em, put = build_sse_runner()

    def run_scraper():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _run():
            try:
                put("Lendo planilha...")
                itens = get_lista_diaria()
                if not itens:
                    put("ERRO: Nenhum produto encontrado na planilha para hoje")
                    return
                put(f"{len(itens)} produto(s) encontrado(s) na planilha")

                async def progress(msg: str):
                    put(msg)

                async with IFrutiScraper() as scraper:
                    put("Login no iFruti...")
                    await scraper.criar_lista_diaria(itens, progress=progress)
            except Exception as e:
                put(f"ERRO: {e}")
            finally:
                msg_queue.put(None)

        loop.run_until_complete(_run())
        loop.close()
        salvar_no_banco(messages, iniciado_em, "lista_diaria")

    threading.Thread(target=run_scraper, daemon=True).start()

    return StreamingResponse(
        make_stream(msg_queue),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/vendas")
async def importar_vendas():
    msg_queue, messages, iniciado_em, put = build_sse_runner()

    def run_scraper():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _run():
            try:
                aba = get_aba_venda_atual()
                put(f"Buscando vendas pendentes na aba {aba}...")
                vendas = get_vendas_nao_importadas(aba)
                if not vendas:
                    put("Nenhuma venda pendente encontrada para hoje")
                    return
                put(f"{len(vendas)} venda(s) encontrada(s)")

                async def progress(msg: str):
                    put(msg)

                async with IFrutiScraper() as scraper:
                    put("Login no iFruti...")
                    await scraper.criar_entradas_pedido(vendas, aba, progress=progress)
            except Exception as e:
                put(f"ERRO: {e}")
            finally:
                msg_queue.put(None)

        loop.run_until_complete(_run())
        loop.close()
        salvar_no_banco(messages, iniciado_em, "vendas")

    threading.Thread(target=run_scraper, daemon=True).start()

    return StreamingResponse(
        make_stream(msg_queue),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/ultimo-log")
def get_ultimo_log(db: Session = Depends(get_db)):
    importacao = (
        db.query(Importacao)
        .filter(or_(Importacao.tipo == "lista_diaria", Importacao.tipo.is_(None)))
        .order_by(Importacao.id.desc())
        .first()
    )
    if not importacao:
        return JSONResponse({"log": None})
    return importacao_to_dict(importacao)


@router.get("/vendas/ultimo-log")
def get_ultimo_log_vendas(db: Session = Depends(get_db)):
    importacao = (
        db.query(Importacao)
        .filter(Importacao.tipo == "vendas")
        .order_by(Importacao.id.desc())
        .first()
    )
    if not importacao:
        return JSONResponse({"log": None})
    return importacao_to_dict(importacao)
