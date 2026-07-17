import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.expense import (
    CATEGORY_ICON_MAX_LENGTH,
    CATEGORY_MAX_LENGTH,
    DEFAULT_CATEGORY,
    SplitMethod,
)


class RecurringExpense(Base):
    """Regla de gasto recurrente mensual (M7): «el alquiler se apunta solo».

    Cada mes, el día indicado, la regla materializa un gasto normal con el
    reparto del momento (percentage usa los default_percentage vigentes ese
    día). La materialización es perezosa: ocurre al consultar gastos o
    balances del grupo — sin cron ni procesos aparte.
    """

    __tablename__ = "recurring_expenses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    description: Mapped[str] = mapped_column(String(500))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    category: Mapped[str] = mapped_column(
        String(CATEGORY_MAX_LENGTH), default=DEFAULT_CATEGORY
    )
    category_icon: Mapped[Optional[str]] = mapped_column(
        String(CATEGORY_ICON_MAX_LENGTH), nullable=True
    )
    paid_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("group_members.id"))
    # solo equal/percentage: los métodos con splits a medida no tienen
    # sentido «para siempre» (validado en el schema)
    split_method: Mapped[SplitMethod] = mapped_column(
        Enum(SplitMethod, native_enum=False, length=20)
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    # día del mes en que se apunta (1–28 para existir en todos los meses)
    day_of_month: Mapped[int] = mapped_column(Integer)
    # próximo mes pendiente de materializar («2026-08»)
    next_period: Mapped[str] = mapped_column(String(7))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    group = relationship("Group")
    paid_by = relationship("GroupMember")
