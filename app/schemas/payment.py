from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.expense import Money
from app.schemas.limites import FechaRazonable, NotaLibre


class PaymentCreate(BaseModel):
    from_member_id: UUID
    to_member_id: UUID
    amount: Money
    paid_at: Optional[FechaRazonable] = None
    note: Optional[NotaLibre] = None


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    group_id: UUID
    from_member_id: UUID
    to_member_id: UUID
    amount: Money
    paid_at: datetime
    note: Optional[str]
