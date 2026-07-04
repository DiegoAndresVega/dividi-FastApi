from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class InvitationCreate(BaseModel):
    # opcional: atar la invitación a un email concreto
    email: Optional[EmailStr] = None
    # opcional: caducidad en días (si no, usa el valor por defecto de config)
    expires_in_days: Optional[int] = Field(default=None, ge=1, le=365)


class InvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    email: Optional[str]
    used_by_id: Optional[UUID]
    used_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_at: datetime
    # enlace listo para compartir (solo si hay frontend_base_url configurado)
    invite_link: Optional[str] = None


class InvitationCheck(BaseModel):
    """Respuesta pública para validar un código antes de mostrar el formulario."""

    valid: bool
    email: Optional[str] = None
    reason: Optional[str] = None
