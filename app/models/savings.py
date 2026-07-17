import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SavingsEntryKind(str, enum.Enum):
    # cierre de un mes: el usuario confirma cuánto logró ahorrar (puede ser 0)
    monthly = "monthly"
    # ajuste manual de la hucha en cualquier momento, positivo o negativo,
    # sin justificación (un imprevisto, dinero con el que no contaba...)
    adjustment = "adjustment"


class SavingsPlan(Base):
    """Plan de ahorro personal (pestaña «Mi dinero»).

    La app no conoce las cuentas reales del usuario, así que la hucha
    (`saved_amount`) no se deduce de gastos: es la suma de confirmaciones
    mensuales y ajustes manuales. Un usuario puede tener varios planes.
    """

    __tablename__ = "savings_plans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(120))
    target_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    monthly_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user = relationship("User")
    entries = relationship(
        "SavingsEntry",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="SavingsEntry.created_at",
    )

    @property
    def saved_amount(self) -> Decimal:
        return sum((entry.amount for entry in self.entries), Decimal("0"))


class SavingsEntry(Base):
    """Movimiento de la hucha de un plan: cierre mensual o ajuste manual."""

    __tablename__ = "savings_entries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("savings_plans.id", ondelete="CASCADE")
    )
    kind: Mapped[SavingsEntryKind] = mapped_column(
        Enum(SavingsEntryKind, native_enum=False, length=20)
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # mes que cierra una confirmación («2026-07»); None en los ajustes
    period: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    plan = relationship("SavingsPlan", back_populates="entries")
