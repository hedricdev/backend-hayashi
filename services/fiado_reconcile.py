from datetime import date

from sqlalchemy.orm import Session

from models.venda_historico import VendaHistorico
from services.historico_import import upsert_historico_rows

_CHAVE = ("data", "cliente", "produto", "qtde", "preco_item")


def _chave_row(row: dict) -> tuple:
    return (row["data"], row["cliente"], row["produto"], row["qtde"], round(float(row["preco_item"] or 0), 2))


def _chave_venda(v: VendaHistorico) -> tuple:
    return (v.data, v.cliente, v.produto, v.qtde, round(float(v.preco_item or 0), 2))


def reconciliar_fiado(db: Session, rows: list[dict]) -> tuple[int, int, int]:
    """Sincroniza vendas_historico com o snapshot completo "Em Aberto" do iFruti.

    1. Upsert das linhas recebidas — confirma quem continua aberto, atualiza
       valor_aberto se mudou (ex: pagamento parcial), e captura fiado que
       ainda não existia no banco.
    2. Reconciliação: qualquer linha com valor_aberto > 0 no nosso banco que
       NÃO aparece nesse snapshot foi paga (o iFruti só lista quem ainda
       deve) — zera o valor_aberto. Sem isso, fiado antigo fica preso aberto
       pra sempre, já que o sync por período (exportar_vendas_periodo) só
       cobre uma janela recente de datas. A data exata do pagamento não é
       capturada por esse caminho — grava data.today() em data_recebimento
       como aproximação (só sabemos que foi pago em algum momento entre o
       último sync e agora).

    Retorna (novos, atualizados, quitados).
    """
    novos, atualizados = upsert_historico_rows(db, rows)

    chaves_abertas = {_chave_row(row) for row in rows}

    abertos_no_banco = db.query(VendaHistorico).filter(VendaHistorico.valor_aberto > 0).all()

    quitados = 0
    for venda in abertos_no_banco:
        if _chave_venda(venda) not in chaves_abertas:
            venda.valor_aberto = 0
            venda.data_recebimento = date.today()
            quitados += 1

    if quitados:
        db.commit()

    return novos, atualizados, quitados
