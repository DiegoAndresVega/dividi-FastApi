from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.expense import ExpenseCategory
from app.schemas.expense import Money


class PersonalExpenseCreate(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    amount: Money
    category: ExpenseCategory = ExpenseCategory.otros
    # opcional: apuntar un gasto de otro día (los gastos hormiga se apuntan tarde)
    created_at: Optional[datetime] = None


class PersonalExpenseUpdate(BaseModel):
    description: Optional[str] = Field(default=None, min_length=1, max_length=500)
    amount: Optional[Money] = None
    category: Optional[ExpenseCategory] = None


class PersonalExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    description: str
    amount: Decimal
    category: ExpenseCategory
    created_at: datetime


class BudgetItem(BaseModel):
    category: ExpenseCategory
    limit_amount: Money


class FinancesUpdate(BaseModel):
    """PUT /me/finances: documento completo (los budgets se reemplazan)."""

    monthly_income: Optional[Money] = None
    budgets: list[BudgetItem] = []


class FinancesOut(BaseModel):
    monthly_income: Optional[Decimal]
    budgets: list[BudgetItem]


class CategorySummary(BaseModel):
    category: ExpenseCategory
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
