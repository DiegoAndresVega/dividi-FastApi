from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.expense import DEFAULT_CATEGORY
from app.schemas.expense import CategoryIcon, CategoryName, Money
from app.schemas.limites import MAX_PRESUPUESTOS, Descripcion, FechaRazonable


class PersonalExpenseCreate(BaseModel):
    description: Descripcion
    amount: Money
    category: CategoryName = DEFAULT_CATEGORY
    category_icon: Optional[CategoryIcon] = None
    # opcional: apuntar un gasto de otro día (los gastos hormiga se apuntan tarde)
    created_at: Optional[FechaRazonable] = None


class PersonalExpenseUpdate(BaseModel):
    description: Optional[Descripcion] = None
    amount: Optional[Money] = None
    category: Optional[CategoryName] = None
    # None con el campo presente = quitar el emoji (el router mira model_fields_set)
    category_icon: Optional[CategoryIcon] = None


class PersonalExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    description: str
    amount: Decimal
    category: str
    category_icon: Optional[str]
    created_at: datetime


class BudgetItem(BaseModel):
    category: CategoryName
    limit_amount: Money


class FinancesUpdate(BaseModel):
    """PUT /me/finances: documento completo (los budgets se reemplazan)."""

    monthly_income: Optional[Money] = None
    budgets: list[BudgetItem] = Field(
        default_factory=list, max_length=MAX_PRESUPUESTOS
    )


class FinancesOut(BaseModel):
    monthly_income: Optional[Decimal]
    budgets: list[BudgetItem]


class CategorySummary(BaseModel):
    category: str
    personal: Decimal
    groups_share: Decimal
    total: Decimal
    budget_limit: Optional[Decimal] = None


class MonthlySummaryOut(BaseModel):
    """El mes completo de verdad: lo personal + tu parte de cada grupo."""

    period: str
    monthly_income: Optional[Decimal]
    personal_total: Decimal
    groups_share_total: Decimal
    total_spent: Decimal
    # nómina − gastado; None si no hay nómina declarada
    available: Optional[Decimal]
    by_category: list[CategorySummary]
