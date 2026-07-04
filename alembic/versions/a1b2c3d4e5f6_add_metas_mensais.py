"""add metas_mensais table

Revision ID: a1b2c3d4e5f6
Revises: f3a4b5c6d7e8
Create Date: 2026-06-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "metas_mensais",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("mes", sa.String(7), nullable=False),
        sa.Column("meta", sa.Numeric(12, 2), nullable=False),
        sa.Column("supermeta", sa.Numeric(12, 2), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=True),
        sa.Column("atualizado_em", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mes", name="uq_meta_mensal_mes"),
    )
    op.create_index("ix_metas_mensais_mes", "metas_mensais", ["mes"])


def downgrade() -> None:
    op.drop_index("ix_metas_mensais_mes", table_name="metas_mensais")
    op.drop_table("metas_mensais")
