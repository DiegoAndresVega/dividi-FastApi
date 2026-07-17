"""Mi dinero: gastos personales, nómina y presupuestos por categoría

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_categoria = sa.Enum(
    "comida",
    "transporte",
    "alojamiento",
    "ocio",
    "otros",
    name="expensecategory",
    native_enum=False,
    length=20,
)


def upgrade() -> None:
    op.create_table(
        "personal_expenses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("category", _categoria, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_personal_expenses_user_id"),
        "personal_expenses",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "user_finances",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("monthly_income", sa.Numeric(12, 2), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "user_budgets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("category", _categoria, nullable=False),
        sa.Column("limit_amount", sa.Numeric(12, 2), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "category"),
    )
    op.create_index(
        op.f("ix_user_budgets_user_id"), "user_budgets", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_budgets_user_id"), table_name="user_budgets")
    op.drop_table("user_budgets")
    op.drop_table("user_finances")
    op.drop_index(op.f("ix_personal_expenses_user_id"), table_name="personal_expenses")
    op.drop_table("personal_expenses")
