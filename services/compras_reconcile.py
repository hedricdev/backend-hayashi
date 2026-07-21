from datetime import date

from sqlalchemy.orm import Session

from models.compra_historico import CompraHistorico
from services.compras_import import upsert_compras_rows

_CHAVE = (
    "data_compra", "produto", "fornecedor", "qtde", "valor_unitario",
    "valor_total", "ocorrencia",
)


def _chave_row(row: dict) -> tuple:
    return tuple(row[k] for k in _CHAVE)


def _chave_compra(c: CompraHistorico) -> tuple:
    return (
        c.data_compra, c.produto, c.fornecedor, c.qtde,
        round(float(c.valor_unitario or 0), 4), round(float(c.valor_total or 0), 2),
        c.ocorrencia,
    )


def reconciliar_compras_aberto(db: Session, rows: list[dict]) -> tuple[int, int, int]:
    """Sincroniza compras_historico com o snapshot completo "Em Aberto" do
    iFruti. Mesmo racional de reconciliar_despesas_aberto/reconciliar_fiado:
    o sync por período (exportar_compras_periodo) só cobre uma janela
    recente de datas, então uma compra antiga que só é paga bem depois
    nunca mais aparece nesse export e ficaria presa em aberto pra sempre.

    A data exata do pagamento não é capturada por esse caminho — grava
    date.today() em data_pagamento como aproximação.

    Retorna (novos, atualizados, quitados).
    """
    novos, atualizados = upsert_compras_rows(db, rows)

    chaves_abertas = {_chave_row(row) for row in rows}

    abertos_no_banco = db.query(CompraHistorico).filter(CompraHistorico.valor_aberto > 0).all()

    quitados = 0
    for compra in abertos_no_banco:
        if _chave_compra(compra) not in chaves_abertas:
            compra.valor_aberto = 0
            compra.data_pagamento = date.today()
            quitados += 1

    if quitados:
        db.commit()

    return novos, atualizados, quitados
