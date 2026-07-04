import asyncio
import json
import queue
from datetime import datetime

from models.importacao import Importacao


def build_sse_runner():
    """Cria a infra de log em stream usada pelos fluxos de importação/sync.

    Retorna (msg_queue, messages, iniciado_em, put) prontos para uso: `put`
    registra a mensagem na lista (para persistir depois) e na fila (para o
    StreamingResponse consumir em tempo real).
    """
    msg_queue: "queue.Queue[str | None]" = queue.Queue()
    messages: list[str] = []
    iniciado_em = datetime.utcnow()

    def put(msg: str):
        messages.append(msg)
        msg_queue.put(msg)

    return msg_queue, messages, iniciado_em, put


def salvar_no_banco(messages: list[str], iniciado_em: datetime, tipo: str):
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


def make_stream(msg_queue: "queue.Queue[str | None]"):
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


def importacao_to_dict(importacao: Importacao) -> dict:
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
