"""Gastos recurrentes mensuales (el alquiler se apunta solo)

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recurring_expenses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "comida",
                "transporte",
                "alojamiento",
                "ocio",
                "otros",
                name="expensecategory",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("paid_by_id", sa.Uuid(), nullable=False),
        sa.Column(
            "split_method",
            sa.Enum(
                "equal",
                "percentage",
                "exact",
                "shares",
                name="splitmethod",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("day_of_month", sa.Integer(), nullable=False),
        sa.Column("next_period", sa.String(length=7), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["paid_by_id"], ["group_members.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_recurring_expenses_group_id"),
        "recurring_expenses",
        ["group_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_recurring_expenses_group_id"), table_name="recurring_expenses"
    )
    op.drop_table("recurring_expenses")
