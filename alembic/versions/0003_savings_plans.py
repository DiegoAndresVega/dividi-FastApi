"""Planes de ahorro personales (pestaña «Mi dinero»)

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "savings_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("target_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("monthly_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_savings_plans_user_id"), "savings_plans", ["user_id"], unique=False
    )
    op.create_table(
        "savings_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "monthly",
                "adjustment",
                name="savingsentrykind",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["savings_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_savings_entries_plan_id"), "savings_entries", ["plan_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_savings_entries_plan_id"), table_name="savings_entries")
    op.drop_table("savings_entries")
    op.drop_index(op.f("ix_savings_plans_user_id"), table_name="savings_plans")
    op.drop_table("savings_plans")
