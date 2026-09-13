from datetime import datetime
from typing import Annotated, Optional
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field
from pydantic_core import PydanticCustomError

from app.security import (
    LONGITUD_MAXIMA_CONTRASENA,
    LONGITUD_MINIMA_CONTRASENA,
    cabe_en_bcrypt,
)


def _cabe_en_bcrypt(password: str) -> str:
    if not cabe_en_bcrypt(password):
        # PydanticCustomError y no ValueError: la app enseña `msg` tal cual, y
        # un ValueError le antepone «Value error, ».
        raise PydanticCustomError(
            "contrasena_demasiado_larga",
            "La contraseña es demasiado larga: como máximo {maximo} caracteres, "
            "y las letras con tilde, la ñ o los emojis cuentan por más de uno",
            {"maximo": LONGITUD_MAXIMA_CONTRASENA},
        )
    return password


# La que se elige, al registrarse o al cambiarla. El máximo se mide en bytes y
# no en caracteres, porque es lo que mide bcrypt: una ñ ocupa dos.
ContrasenaNueva = Annotated[
    str,
    Field(min_length=LONGITUD_MINIMA_CONTRASENA),
    AfterValidator(_cabe_en_bcrypt),
]


class UserCreate(BaseModel):
    email: EmailStr
    password: ContrasenaNueva
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
    new_password: ContrasenaNueva


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str
