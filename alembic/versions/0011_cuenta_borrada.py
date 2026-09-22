"""Marca de cuenta borrada, para el derecho de supresión del RGPD

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # La fila del usuario no se puede borrar: los gastos de grupo apuntan a
    # ella y son datos de los demás miembros. Queda una lápida sin datos
    # personales, y esta columna es lo que la distingue de una cuenta viva.
    op.add_column(
        "users",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "deleted_at")
