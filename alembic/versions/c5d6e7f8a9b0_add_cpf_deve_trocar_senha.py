"""add cpf e deve_trocar_senha to usuarios

Revision ID: c5d6e7f8a9b0
Revises: b434b7ecffb0
Create Date: 2026-05-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "b434b7ecffb0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("usuarios", sa.Column("cpf", sa.String(length=14), nullable=True))
    # server_default='false' — usuários existentes (admin) não precisam trocar senha
    op.add_column(
        "usuarios",
        sa.Column(
            "deve_trocar_senha",
            sa.Boolean(),
            nullable=True,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("usuarios", "deve_trocar_senha")
    op.drop_column("usuarios", "cpf")
