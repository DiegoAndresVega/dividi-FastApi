from datetime import datetime
from decimal import Decimal
from typing import Annotated, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.expense import ExpenseCategory, SplitMethod
from app.schemas.group import CurrencyCode, Percentage

Money = Annotated[Decimal, Field(gt=0, le=Decimal("9999999999"), decimal_places=2)]


class SplitInput(BaseModel):
    group_member_id: UUID
    percentage: Optional[Percentage] = None
    exact_amount: Optional[Decimal] = Field(default=None, ge=0, decimal_places=2)
    shares: Optional[int] = Field(default=None, gt=0)


class ExpenseCreate(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    amount: Money
    currency: Optional[CurrencyCode] = None
    category: ExpenseCategory = ExpenseCategory.otros
    paid_by: UUID
    split_method: SplitMethod
    # opcional para "equal" (por defecto: todos los miembros) y "percentage"
    # (por defecto: default_percentage de cada miembro del grupo);
    # obligatorio para "exact" y "shares"
    splits: Optional[list[SplitInput]] = None


class ExpenseUpdate(BaseModel):
    description: Optional[str] = Field(default=None, min_length=1, max_length=500)
    amount: Optional[Money] = None
    currency: Optional[CurrencyCode] = None
    category: Optional[ExpenseCategory] = None
    paid_by: Optional[UUID] = None
    split_method: Optional[SplitMethod] = None
    splits: Optional[list[SplitInput]] = None


class SplitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    group_member_id: UUID
    percentage: Optional[Decimal]
    exact_amount: Optional[Decimal]
    shares: Optional[int]
    computed_amount: Decimal


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    group_id: UUID
    description: str
    amount: Decimal
    currency: str
    category: ExpenseCategory
    paid_by_id: UUID
    split_method: SplitMethod
    created_by_id: UUID
    created_at: datetime
    receipt_image_url: Optional[str]
    splits: list[SplitOut]
