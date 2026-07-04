from sqlalchemy import column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from models.venda_historico import VendaHistorico
from services.categoria_map import classificar

_CHAVE = ("data", "cliente", "produto", "qtde", "preco_item")


def upsert_historico_rows(
    db: Session, rows: list[dict], batch_size: int = 2000
) -> tuple[int, int]:
    """Insere ou atualiza linhas de vendas_historico em lote.

    Usa a UniqueConstraint (data, cliente, produto, qtde, preco_item) via
    INSERT ... ON CONFLICT: em conflito, só atualiza valor_aberto e
    data_recebimento (os únicos campos que mudam depois do lançamento
    original — ex: fiado que foi pago). Deduplica o próprio lote de entrada
    primeiro, já que arquivos/exportações podem se sobrepor.

    Retorna (importados, atualizados).
    """
    seen: dict[tuple, dict] = {}
    for row in rows:
        seen[tuple(row[k] for k in _CHAVE)] = row
    unique_rows = list(seen.values())
    if not unique_rows:
        return 0, 0

    table = VendaHistorico.__table__
    importados = 0
    atualizados = 0

    for i in range(0, len(unique_rows), batch_size):
        batch = unique_rows[i : i + batch_size]
        values = []
        for row in batch:
            cat, forn = classificar(row["produto"])
            values.append({**row, "categoria": cat, "fornecedor": forn})

        stmt = pg_insert(table).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=list(_CHAVE),
            set_={
                "valor_aberto": stmt.excluded.valor_aberto,
                "data_recebimento": stmt.excluded.data_recebimento,
            },
        ).returning((column("xmax") == 0).label("inserted"))

        for (inserted,) in db.execute(stmt):
            if inserted:
                importados += 1
            else:
                atualizados += 1
        db.commit()

    return importados, atualizados
