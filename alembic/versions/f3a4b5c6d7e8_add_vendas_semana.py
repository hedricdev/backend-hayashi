"""add vendas_semana table

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-06-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vendas_semana",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("semana_ref", sa.Date(), nullable=False),
        sa.Column("data", sa.Date(), nullable=False),
        sa.Column("dia_semana", sa.String(10), nullable=False),
        sa.Column("vendedor", sa.String(100), nullable=False),
        sa.Column("cliente", sa.String(200), nullable=False),
        sa.Column("produto", sa.String(200), nullable=False),
        sa.Column("quantidade", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pagamento", sa.String(50), nullable=True),
        sa.Column("faturamento_estimado", sa.Numeric(10, 2), nullable=True),
        sa.Column("importado_em", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "semana_ref", "dia_semana", "vendedor", "cliente", "produto", "quantidade",
            name="uq_venda_semana",
        ),
    )
    op.create_index("ix_vendas_semana_semana_ref", "vendas_semana", ["semana_ref"])
    op.create_index("ix_vendas_semana_data", "vendas_semana", ["data"])
    op.create_index("ix_vendas_semana_vendedor", "vendas_semana", ["vendedor"])
    op.create_index("ix_vendas_semana_cliente", "vendas_semana", ["cliente"])


def downgrade() -> None:
    op.drop_index("ix_vendas_semana_cliente", table_name="vendas_semana")
    op.drop_index("ix_vendas_semana_vendedor", table_name="vendas_semana")
    op.drop_index("ix_vendas_semana_data", table_name="vendas_semana")
    op.drop_index("ix_vendas_semana_semana_ref", table_name="vendas_semana")
    op.drop_table("vendas_semana")
