"""add lucro columns to metas_mensais

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("metas_mensais", sa.Column("lucro", sa.Numeric(12, 2), nullable=True))
    op.add_column("metas_mensais", sa.Column("lucro_margem_pct", sa.Numeric(5, 2), nullable=True))
    op.add_column("metas_mensais", sa.Column("lucro_atualizado_em", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("metas_mensais", "lucro_atualizado_em")
    op.drop_column("metas_mensais", "lucro_margem_pct")
    op.drop_column("metas_mensais", "lucro")
