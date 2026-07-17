import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.expense import (
    CATEGORY_ICON_MAX_LENGTH,
    CATEGORY_MAX_LENGTH,
    DEFAULT_CATEGORY,
)


class PersonalExpense(Base):
    """Gasto de puertas adentro (pestaña «Mi dinero»): no se comparte con
    nadie ni toca ningún grupo. Reutiliza las categorías de los gastos."""

    __tablename__ = "personal_expenses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    description: Mapped[str] = mapped_column(String(500))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    category: Mapped[str] = mapped_column(
        String(CATEGORY_MAX_LENGTH), default=DEFAULT_CATEGORY
    )
    category_icon: Mapped[Optional[str]] = mapped_column(
        String(CATEGORY_ICON_MAX_LENGTH), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user = relationship("User")


class UserFinance(Base):
    """Configuración financiera personal: la nómina mensual declarada."""

    __tablename__ = "user_finances"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    monthly_income: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    user = relationship("User")


class UserBudget(Base):
    """Techo de gasto mensual por categoría (uno por categoría y usuario)."""

    __tablename__ = "user_budgets"
    __table_args__ = (UniqueConstraint("user_id", "category"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(CATEGORY_MAX_LENGTH))
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    user = relationship("User")
