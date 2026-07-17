"""Categorías libres con emoji: category pasa a texto libre y aparece
category_icon (el emoji de las categorías inventadas, p. ej. «agua» → 💧)

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Las columnas category eran VARCHAR(20) (enum no nativo, sin CHECK): basta
# con ensancharlas; los valores existentes («alojamiento» incluido) siguen
# siendo válidos como texto libre.
_TABLAS_CON_CATEGORIA = (
    "expenses",
    "personal_expenses",
    "recurring_expenses",
    "user_budgets",
)
_TABLAS_CON_ICONO = ("expenses", "personal_expenses", "recurring_expenses")


def upgrade() -> None:
    for tabla in _TABLAS_CON_CATEGORIA:
        op.alter_column(
            tabla,
            "category",
            existing_type=sa.String(length=20),
            type_=sa.String(length=30),
            existing_nullable=False,
        )
    for tabla in _TABLAS_CON_ICONO:
        op.add_column(
            tabla, sa.Column("category_icon", sa.String(length=20), nullable=True)
        )


def downgrade() -> None:
    for tabla in _TABLAS_CON_ICONO:
        op.drop_column(tabla, "category_icon")
    for tabla in _TABLAS_CON_CATEGORIA:
        op.alter_column(
            tabla,
            "category",
            existing_type=sa.String(length=30),
            type_=sa.String(length=20),
            existing_nullable=False,
        )
