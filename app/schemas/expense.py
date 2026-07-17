from datetime import datetime
from decimal import Decimal
from typing import Annotated, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.expense import (
    CATEGORY_ICON_MAX_LENGTH,
    CATEGORY_MAX_LENGTH,
    DEFAULT_CATEGORY,
    SplitMethod,
)
from app.schemas.group import CurrencyCode, Percentage

Money = Annotated[Decimal, Field(gt=0, le=Decimal("9999999999"), decimal_places=2)]

# Nombre de categoría: libre pero normalizado (sin espacios sobrantes y en
# minúsculas) para que «Agua» y «agua» sean la misma a la hora de agrupar.
CategoryName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=1,
        max_length=CATEGORY_MAX_LENGTH,
    ),
]
# Emoji que acompaña a una categoría inventada («agua» → 💧).
CategoryIcon = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=CATEGORY_ICON_MAX_LENGTH
    ),
]


class SplitInput(BaseModel):
    group_member_id: UUID
    percentage: Optional[Percentage] = None
    exact_amount: Optional[Decimal] = Field(default=None, ge=0, decimal_places=2)
    shares: Optional[int] = Field(default=None, gt=0)


class ExpenseCreate(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    amount: Money
    currency: Optional[CurrencyCode] = None
    category: CategoryName = DEFAULT_CATEGORY
    category_icon: Optional[CategoryIcon] = None
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
    category: Optional[CategoryName] = None
    # None con el campo presente = quitar el emoji (p. ej. al volver a una
    # categoría predefinida); el router mira model_fields_set
    category_icon: Optional[CategoryIcon] = None
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
    category: str
    category_icon: Optional[str]
    paid_by_id: UUID
    split_method: SplitMethod
    created_by_id: UUID
    created_at: datetime
    receipt_image_url: Optional[str]
    splits: list[SplitOut]
