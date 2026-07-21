from sqlalchemy import column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from models.despesa_historico import DespesaHistorico

_CHAVE = ("data_despesa", "descricao", "loja", "credor", "data_vencimento", "valor", "ocorrencia")


def upsert_despesas_rows(
    db: Session, rows: list[dict], batch_size: int = 2000
) -> tuple[int, int]:
    """Insere ou atualiza linhas de despesas_historico em lote.

    Usa a UniqueConstraint (data_despesa, descricao, loja, credor,
    data_vencimento, valor, ocorrencia) via INSERT ... ON CONFLICT: em
    conflito, só atualiza valor_aberto e data_pagamento (os únicos campos que
    mudam depois do lançamento original — despesa que estava em aberto foi
    paga). Deduplica o próprio lote de entrada primeiro, já que
    arquivos/exportações podem se sobrepor.

    Retorna (importados, atualizados).
    """
    seen: dict[tuple, dict] = {}
    for row in rows:
        seen[tuple(row[k] for k in _CHAVE)] = row
    unique_rows = list(seen.values())
    if not unique_rows:
        return 0, 0

    table = DespesaHistorico.__table__
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
