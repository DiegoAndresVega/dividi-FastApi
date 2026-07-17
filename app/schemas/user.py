from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    # bcrypt trunca a 72 bytes, limitamos la longitud máxima
    password: str = Field(min_length=8, max_length=72)
    name: str = Field(min_length=1, max_length=255)
    # código de invitación (obligatorio salvo para el fundador o si se
    # desactiva require_invite en config)
    invite_code: Optional[str] = Field(default=None, max_length=64)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    name: str
    created_at: datetime


class UserUpdate(BaseModel):
    """Campos editables del propio perfil (PATCH /me)."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)


class PasswordChange(BaseModel):
    current_password: str
    # mismas reglas que en el registro (bcrypt trunca a 72 bytes)
    new_password: str = Field(min_length=8, max_length=72)


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str
