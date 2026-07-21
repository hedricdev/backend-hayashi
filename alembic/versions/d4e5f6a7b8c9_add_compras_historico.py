"""add compras_historico table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "compras_historico",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("data_compra", sa.Date(), nullable=False),
        sa.Column("produto", sa.String(200), nullable=False),
        sa.Column("fornecedor", sa.String(200), nullable=False),
        sa.Column("qtde", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valor_unitario", sa.Numeric(12, 4), nullable=True),
        sa.Column("valor_total", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("valor_aberto", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("data_pagamento", sa.Date(), nullable=True),
        sa.Column("devolucao", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ocorrencia", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("importado_em", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "data_compra", "produto", "fornecedor", "qtde", "valor_unitario",
            "valor_total", "ocorrencia",
            name="uq_compra_historico",
        ),
    )
    op.create_index("ix_compras_historico_data_compra", "compras_historico", ["data_compra"])
    op.create_index("ix_compras_historico_produto", "compras_historico", ["produto"])
    op.create_index("ix_compras_historico_fornecedor", "compras_historico", ["fornecedor"])


def downgrade() -> None:
    op.drop_index("ix_compras_historico_fornecedor", table_name="compras_historico")
    op.drop_index("ix_compras_historico_produto", table_name="compras_historico")
    op.drop_index("ix_compras_historico_data_compra", table_name="compras_historico")
    op.drop_table("compras_historico")
