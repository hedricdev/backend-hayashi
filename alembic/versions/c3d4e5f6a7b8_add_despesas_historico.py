"""add despesas_historico table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "despesas_historico",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("data_despesa", sa.Date(), nullable=False),
        sa.Column("descricao", sa.String(200), nullable=False),
        sa.Column("loja", sa.String(100), nullable=False),
        sa.Column("credor", sa.String(200), nullable=False),
        sa.Column("data_vencimento", sa.Date(), nullable=True),
        sa.Column("valor", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("valor_aberto", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("data_pagamento", sa.Date(), nullable=True),
        sa.Column("ocorrencia", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("importado_em", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "data_despesa", "descricao", "loja", "credor", "data_vencimento",
            "valor", "ocorrencia",
            name="uq_despesa_historico",
        ),
    )
    op.create_index("ix_despesas_historico_data_despesa", "despesas_historico", ["data_despesa"])
    op.create_index("ix_despesas_historico_descricao", "despesas_historico", ["descricao"])


def downgrade() -> None:
    op.drop_index("ix_despesas_historico_descricao", table_name="despesas_historico")
    op.drop_index("ix_despesas_historico_data_despesa", table_name="despesas_historico")
    op.drop_table("despesas_historico")
