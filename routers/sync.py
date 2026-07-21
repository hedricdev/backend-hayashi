import asyncio
import threading

from fastapi import APIRouter, Depends, HTTPException

from fastapi.responses import StreamingResponse

from auth import get_current_user
from models.usuario import Role, Usuario
from services.auto_sync import executar_sync_completo
from services.sse_log import build_sse_runner, make_stream

router = APIRouter()


@router.post("/completo")
async def sync_completo(
    current_user: Usuario = Depends(get_current_user),
):
    """Roda os 4 fluxos de sincronização (vendas, fiado, despesas, compras)
    em sequência, sob demanda — mesma rotina do job automático de 1h.
    Usado pelo botão "Atualizar" do Dashboard pra trazer tudo de uma vez.

    Cada fluxo já salva seu próprio log em `importacoes` (mesmo `tipo` dos
    syncs individuais), então não há um log agregado aqui — só o streaming
    de progresso pro frontend acompanhar em tempo real.
    """
    if current_user.role != Role.admin:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")

    msg_queue, _messages, _iniciado_em, put = build_sse_runner()

    def run_scraper():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(executar_sync_completo(put=put))
        loop.close()
        msg_queue.put(None)

    threading.Thread(target=run_scraper, daemon=True).start()

    return StreamingResponse(
        make_stream(msg_queue),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
