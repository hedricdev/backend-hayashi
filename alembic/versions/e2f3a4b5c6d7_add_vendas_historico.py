"""add vendas_historico table

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-06-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vendas_historico",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("data", sa.Date(), nullable=False),
        sa.Column("cliente", sa.String(200), nullable=False),
        sa.Column("produto", sa.String(200), nullable=False),
        sa.Column("qtde", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dvl", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("preco_item", sa.Numeric(10, 2), nullable=True),
        sa.Column("total_item", sa.Numeric(10, 2), nullable=True),
        sa.Column("valor_aberto", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("data_recebimento", sa.Date(), nullable=True),
        sa.Column("categoria", sa.String(100), nullable=True),
        sa.Column("fornecedor", sa.String(100), nullable=True),
        sa.Column("importado_em", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "data", "cliente", "produto", "qtde", "preco_item",
            name="uq_venda_historico",
        ),
    )
    op.create_index("ix_vendas_historico_data", "vendas_historico", ["data"])
    op.create_index("ix_vendas_historico_cliente", "vendas_historico", ["cliente"])


def downgrade() -> None:
    op.drop_index("ix_vendas_historico_cliente", table_name="vendas_historico")
    op.drop_index("ix_vendas_historico_data", table_name="vendas_historico")
    op.drop_table("vendas_historico")
