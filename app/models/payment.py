import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Payment(Base):
    """Un pago real entre dos personas para saldar deudas. NO es un gasto."""

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE")
    )
    from_member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("group_members.id"))
    to_member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("group_members.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # quién apuntó el pago. Nullable a propósito: las filas anteriores a la
    # migración 0009 no lo saben, y borrar al usuario no debe llevarse el pago
    # por delante (el saldo es del grupo, no suyo).
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    group = relationship("Group", back_populates="payments")
    from_member = relationship("GroupMember", foreign_keys=[from_member_id])
    to_member = relationship("GroupMember", foreign_keys=[to_member_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
