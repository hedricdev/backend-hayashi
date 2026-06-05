import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models.importacao import Importacao
from models.usuario import Usuario

router = APIRouter()


class StatusResponse(BaseModel):
    status: str
    iniciado_em: datetime | None
    finalizado_em: datetime | None
    total_importado: int
    total_erro: int
    log: list[str]


@router.get("", response_model=StatusResponse)
def status(
    _: Annotated[Usuario, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    importacao = (
        db.query(Importacao)
        .order_by(Importacao.iniciado_em.desc())
        .first()
    )

    if not importacao:
        return StatusResponse(
            status="nenhuma_importacao",
            iniciado_em=None,
            finalizado_em=None,
            total_importado=0,
            total_erro=0,
            log=[],
        )

    return StatusResponse(
        status=importacao.status,
        iniciado_em=importacao.iniciado_em,
        finalizado_em=importacao.finalizado_em,
        total_importado=importacao.total_importado,
        total_erro=importacao.total_erro,
        log=json.loads(importacao.log or "[]"),
    )
