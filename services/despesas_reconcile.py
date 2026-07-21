from datetime import date

from sqlalchemy.orm import Session

from models.despesa_historico import DespesaHistorico
from services.despesas_import import upsert_despesas_rows

_CHAVE = ("data_despesa", "descricao", "loja", "credor", "data_vencimento", "valor", "ocorrencia")


def _chave_row(row: dict) -> tuple:
    return tuple(row[k] for k in _CHAVE)


def _chave_despesa(d: DespesaHistorico) -> tuple:
    return (
        d.data_despesa, d.descricao, d.loja, d.credor, d.data_vencimento,
        round(float(d.valor or 0), 2), d.ocorrencia,
    )


def reconciliar_despesas_aberto(db: Session, rows: list[dict]) -> tuple[int, int, int]:
    """Sincroniza despesas_historico com o snapshot completo "Em Aberto" do iFruti.

    Mesmo racional de reconciliar_fiado (services/fiado_reconcile.py): o
    sync por período (exportar_despesas_periodo) só cobre uma janela recente
    de datas, então uma despesa antiga que só é paga bem depois nunca mais
    aparece nesse export e ficaria presa em aberto pra sempre. Essa
    reconciliação usa o snapshot sem filtro de data (exportar_despesas_em_aberto)
    pra detectar quem sumiu da lista — ou seja, foi pago.

    A data exata do pagamento não é capturada por esse caminho (só sabemos
    que foi pago em algum momento entre o último sync e agora) — grava
    `date.today()` em data_pagamento como aproximação.

    Retorna (novos, atualizados, quitados).
    """
    novos, atualizados = upsert_despesas_rows(db, rows)

    chaves_abertas = {_chave_row(row) for row in rows}

    abertos_no_banco = db.query(DespesaHistorico).filter(DespesaHistorico.valor_aberto > 0).all()

    quitados = 0
    for despesa in abertos_no_banco:
        if _chave_despesa(despesa) not in chaves_abertas:
            despesa.valor_aberto = 0
            despesa.data_pagamento = date.today()
            quitados += 1

    if quitados:
        db.commit()

    return novos, atualizados, quitados
