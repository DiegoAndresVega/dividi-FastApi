import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ExpenseCategory(str, enum.Enum):
    comida = "comida"
    transporte = "transporte"
    alojamiento = "alojamiento"
    ocio = "ocio"
    otros = "otros"


class SplitMethod(str, enum.Enum):
    equal = "equal"
    percentage = "percentage"
    exact = "exact"
    shares = "shares"


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE")
    )
    description: Mapped[str] = mapped_column(String(500))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    category: Mapped[ExpenseCategory] = mapped_column(
        Enum(ExpenseCategory, native_enum=False, length=20),
        default=ExpenseCategory.otros,
    )
    paid_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("group_members.id"))
    split_method: Mapped[SplitMethod] = mapped_column(
        Enum(SplitMethod, native_enum=False, length=20)
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    receipt_image_url: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )

    group = relationship("Group", back_populates="expenses")
    paid_by = relationship("GroupMember", foreign_keys=[paid_by_id])
    splits = relationship(
        "ExpenseSplit", back_populates="expense", cascade="all, delete-orphan"
    )


class ExpenseSplit(Base):
    __tablename__ = "expense_splits"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    expense_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("expenses.id", ondelete="CASCADE")
    )
    group_member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("group_members.id"))
    # override del default_percentage del grupo (solo split_method = "percentage")
    percentage: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    exact_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    shares: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # importe final ya calculado, para no recalcular en cada lectura
    computed_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    expense = relationship("Expense", back_populates="splits")
    member = relationship("GroupMember")
