"""Fallos de login por cuenta, para frenar la fuerza bruta repartida entre IPs

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # La clave es la huella sha256 del email, no el email: en esta tabla acaban
    # también los correos que alguien teclee sin tener cuenta aquí.
    op.create_table(
        "login_attempts",
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("fallos", sa.Integer(), nullable=False),
        sa.Column("ultimo_fallo_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bloqueado_hasta", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("email_hash"),
    )
    # la poda de filas viejas barre por esta columna en cada login correcto
    op.create_index(
        "ix_login_attempts_ultimo_fallo_at", "login_attempts", ["ultimo_fallo_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_login_attempts_ultimo_fallo_at", table_name="login_attempts")
    op.drop_table("login_attempts")
