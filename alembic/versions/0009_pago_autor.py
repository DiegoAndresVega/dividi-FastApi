"""Quién registró cada pago, para poder restringir quién lo deshace

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable y sin relleno: de los pagos ya existentes no se sabe quién los
    # apuntó, e inventarse un autor sería peor que dejarlo en blanco. Un nulo
    # significa «no se sabe», y entonces mandan los implicados y el admin.
    op.add_column("payments", sa.Column("created_by_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_payments_created_by_id_users",
        "payments",
        "users",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_payments_created_by_id_users", "payments", type_="foreignkey")
    op.drop_column("payments", "created_by_id")
