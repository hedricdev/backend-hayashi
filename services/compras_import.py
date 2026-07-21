from sqlalchemy import column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from models.compra_historico import CompraHistorico

_CHAVE = (
    "data_compra", "produto", "fornecedor", "qtde", "valor_unitario",
    "valor_total", "ocorrencia",
)


def upsert_compras_rows(
    db: Session, rows: list[dict], batch_size: int = 2000
) -> tuple[int, int]:
    """Insere ou atualiza linhas de compras_historico em lote.

    Usa a UniqueConstraint (data_compra, produto, fornecedor, qtde,
    valor_unitario, valor_total, ocorrencia) via INSERT ... ON CONFLICT: em
    conflito, só atualiza valor_aberto e data_pagamento (os únicos campos
    que mudam depois do lançamento original — compra que estava em aberto
    foi paga). Deduplica o próprio lote de entrada primeiro, já que
    arquivos/exportações podem se sobrepor.

    Retorna (importados, atualizados).
    """
    seen: dict[tuple, dict] = {}
    for row in rows:
        seen[tuple(row[k] for k in _CHAVE)] = row
    unique_rows = list(seen.values())
    if not unique_rows:
        return 0, 0

    table = CompraHistorico.__table__
    importados = 0
    atualizados = 0

    for i in range(0, len(unique_rows), batch_size):
        batch = unique_rows[i : i + batch_size]

        stmt = pg_insert(table).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=list(_CHAVE),
            set_={
                "valor_aberto": stmt.excluded.valor_aberto,
                "data_pagamento": stmt.excluded.data_pagamento,
            },
        ).returning((column("xmax") == 0).label("inserted"))

        for (inserted,) in db.execute(stmt):
            if inserted:
                importados += 1
            else:
                atualizados += 1
        db.commit()

    return importados, atualizados
