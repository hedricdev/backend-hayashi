import asyncio
import json
import queue
import threading
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from models.importacao import Importacao
from services.scraping import IFrutiScraper
from services.sheets import get_lista_diaria, get_vendas_nao_importadas, get_aba_atual, get_aba_venda_atual

router = APIRouter()


def _build_sse_runner(tipo: str):
    """Retorna (msg_queue, messages, iniciado_em, put, run_thread) prontos para usar."""
    msg_queue: queue.Queue[str | None] = queue.Queue()
    messages: list[str] = []
    iniciado_em = datetime.utcnow()

    def put(msg: str):
        messages.append(msg)
        msg_queue.put(msg)

    return msg_queue, messages, iniciado_em, put


def _salvar_no_banco(messages: list[str], iniciado_em: datetime, tipo: str):
    finalizado_em = datetime.utcnow()
    total_erro = sum(1 for m in messages if m.startswith("ERRO") or m.startswith("✗"))
    total_importado = sum(1 for m in messages if m.startswith("✓"))
    status = "erro" if total_erro > 0 else "sucesso"

    from database import SessionLocal
    db = SessionLocal()
    try:
        importacao = Importacao(
            iniciado_em=iniciado_em,
            finalizado_em=finalizado_em,
            status=status,
            total_importado=total_importado,
            total_erro=total_erro,
            log=json.dumps(messages, ensure_ascii=False),
            tipo=tipo,
        )
        db.add(importacao)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _make_stream(msg_queue: queue.Queue):
    async def stream():
        while True:
            try:
                msg = msg_queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.1)
                continue
            if msg is None:
                break
            yield f"data: {json.dumps({'msg': msg})}\n\n"

    return stream()


@router.post("/lista-diaria")
async def importar_lista_diaria():
    msg_queue, messages, iniciado_em, put = _build_sse_runner("lista_diaria")

    def run_scraper():
        loop = asyncio.ProactorEventLoop()
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
        _salvar_no_banco(messages, iniciado_em, "lista_diaria")

    threading.Thread(target=run_scraper, daemon=True).start()

    return StreamingResponse(
        _make_stream(msg_queue),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/vendas")
async def importar_vendas():
    msg_queue, messages, iniciado_em, put = _build_sse_runner("vendas")

    def run_scraper():
        loop = asyncio.ProactorEventLoop()
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
        _salvar_no_banco(messages, iniciado_em, "vendas")

    threading.Thread(target=run_scraper, daemon=True).start()

    return StreamingResponse(
        _make_stream(msg_queue),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/ultimo-log")
def get_ultimo_log(db: Session = Depends(get_db)):
    from sqlalchemy import or_
    importacao = (
        db.query(Importacao)
        .filter(or_(Importacao.tipo == "lista_diaria", Importacao.tipo.is_(None)))
        .order_by(Importacao.id.desc())
        .first()
    )
    if not importacao:
        return JSONResponse({"log": None})
    return _importacao_to_dict(importacao)


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
    return _importacao_to_dict(importacao)


def _importacao_to_dict(importacao: Importacao) -> dict:
    return {
        "id": importacao.id,
        "status": importacao.status,
        "tipo": importacao.tipo,
        "iniciado_em": importacao.iniciado_em.isoformat() if importacao.iniciado_em else None,
        "finalizado_em": importacao.finalizado_em.isoformat() if importacao.finalizado_em else None,
        "total_importado": importacao.total_importado,
        "total_erro": importacao.total_erro,
        "log": json.loads(importacao.log) if importacao.log else [],
    }
