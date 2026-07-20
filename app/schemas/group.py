from datetime import datetime
from decimal import Decimal
from typing import Annotated, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models.group import MemberRole

Percentage = Annotated[Decimal, Field(ge=0, le=100, decimal_places=2)]
CurrencyCode = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class GroupMemberInit(BaseModel):
    """Participante que se crea junto con el grupo.

    Puede ser un amigo con cuenta (`user_id`) o un participante personalizado
    sin cuenta (solo un nombre; email opcional para vincularlo si algún día se
    registra).
    """

    display_name: str = Field(min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    # id de un amigo (usuario con cuenta) para añadirlo enlazado a su cuenta
    user_id: Optional[UUID] = None
    default_percentage: Percentage = Decimal("0")


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    default_currency: CurrencyCode = "EUR"
    # peso del creador en el hogar; si se añaden invitados y no se indica, se
    # calcula como el resto hasta 100
    owner_percentage: Optional[Percentage] = None
    # invitados a crear junto con el grupo (además del creador)
    members: list[GroupMemberInit] = Field(default_factory=list)


class GroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    default_currency: Optional[CurrencyCode] = None


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: Optional[UUID]
    invited_email: Optional[str]
    display_name: str
    default_percentage: Decimal
    role: MemberRole
    joined_at: datetime


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    owner_id: UUID
    default_currency: str
    created_at: datetime
    members: list[MemberOut] = []


class MemberAdd(BaseModel):
    """Añadir miembro: por email (usuario existente o invitado que aún no se ha
    registrado) o solo con display_name (invitado sin email).

    `rebalance` permite ajustar en la misma operación los porcentajes del resto
    de miembros para que el total siga sumando 100.
    """

    email: Optional[EmailStr] = None
    # id de un amigo (usuario con cuenta) para añadirlo enlazado a su cuenta
    user_id: Optional[UUID] = None
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    default_percentage: Percentage = Decimal("0")
    rebalance: Optional[dict[UUID, Percentage]] = None

    @model_validator(mode="after")
    def _identifica_al_miembro(self):
        if not self.email and not self.display_name and not self.user_id:
            raise ValueError("Debes indicar 'email', 'display_name' o 'user_id'")
        return self


class MemberUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    role: Optional[MemberRole] = None
    default_percentage: Optional[Percentage] = None
    rebalance: Optional[dict[UUID, Percentage]] = None


class MemberRemove(BaseModel):
    rebalance: Optional[dict[UUID, Percentage]] = None


class BalanceOut(BaseModel):
    member_id: UUID
    display_name: str
    balance: Decimal


class SettlementOut(BaseModel):
    from_member_id: UUID
    from_display_name: str
    to_member_id: UUID
    to_display_name: str
    amount: Decimal
