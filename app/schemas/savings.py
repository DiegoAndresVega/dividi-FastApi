from datetime import datetime
from decimal import Decimal
from typing import Annotated, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.savings import SavingsEntryKind
from app.schemas.expense import Money
from app.schemas.limites import MAX_IMPORTE, NombreDePlan, Periodo as Period

# Cantidad que admite 0 (hucha inicial, o un mes en el que no se logró nada).
NonNegativeMoney = Annotated[Decimal, Field(ge=0, le=MAX_IMPORTE, decimal_places=2)]
# Cantidad con signo: los ajustes de la hucha pueden restar.
SignedMoney = Annotated[Decimal, Field(ge=-MAX_IMPORTE, le=MAX_IMPORTE, decimal_places=2)]


class SavingsPlanCreate(BaseModel):
    name: NombreDePlan
    target_amount: Money
    monthly_amount: Money
    # dinero ya apartado al crear el plan (opcional)
    saved_amount: NonNegativeMoney = Decimal("0")


class SavingsPlanUpdate(BaseModel):
    name: Optional[NombreDePlan] = None
    target_amount: Optional[Money] = None
    monthly_amount: Optional[Money] = None


class SavingsEntryCreate(BaseModel):
    kind: SavingsEntryKind
    amount: SignedMoney
    # solo para `monthly`; si falta, se asume el mes en curso
    period: Optional[Period] = None


class SavingsEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: SavingsEntryKind
    amount: Decimal
    period: Optional[str]
    created_at: datetime


class SavingsPlanOut(BaseModel):
    id: UUID
    name: str
    target_amount: Decimal
    monthly_amount: Decimal
    saved_amount: Decimal
    remaining_amount: Decimal
    months_to_goal: int
    projected_period: str
    current_period: str
    is_current_period_confirmed: bool
    is_completed: bool
    created_at: datetime


class SavingsPlanDetail(SavingsPlanOut):
    entries: list[SavingsEntryOut]
