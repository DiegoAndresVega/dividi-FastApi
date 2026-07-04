from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.expense import Money


class PaymentCreate(BaseModel):
    from_member_id: UUID
    to_member_id: UUID
    amount: Money
    paid_at: Optional[datetime] = None
    note: Optional[str] = Field(default=None, max_length=500)


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    group_id: UUID
    from_member_id: UUID
    to_member_id: UUID
    amount: Money
    paid_at: datetime
    note: Optional[str]
