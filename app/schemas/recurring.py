from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.expense import DEFAULT_CATEGORY
from app.schemas.expense import CategoryIcon, CategoryName, Money
from app.schemas.limites import Descripcion, Periodo as Period

# 1–28 para que el día exista en todos los meses (adiós, 31 de febrero)
DayOfMonth = Annotated[int, Field(ge=1, le=28)]


class RecurringCreate(BaseModel):
    description: Descripcion
    amount: Money
    category: CategoryName = DEFAULT_CATEGORY
    category_icon: Optional[CategoryIcon] = None
    paid_by: UUID
    # solo repartos sin splits a medida: iguales o por Ingresos del grupo
    split_method: Literal["equal", "percentage"] = "percentage"
    day_of_month: DayOfMonth = 1
    # primer mes a materializar; por defecto: este mes si el día no pasó aún
    start_period: Optional[Period] = None


class RecurringUpdate(BaseModel):
    description: Optional[Descripcion] = None
    amount: Optional[Money] = None
    category: Optional[CategoryName] = None
    # None con el campo presente = quitar el emoji (el router mira model_fields_set)
    category_icon: Optional[CategoryIcon] = None
    day_of_month: Optional[DayOfMonth] = None
    active: Optional[bool] = None


class RecurringOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    description: str
    amount: Decimal
    category: str
    category_icon: Optional[str]
    paid_by_id: UUID
    split_method: str
    day_of_month: int
    next_period: str
    active: bool
    created_at: datetime
