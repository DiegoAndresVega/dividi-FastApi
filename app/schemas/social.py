from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr


# ------------------------------------------------------------------ amigos


class FriendRequestCreate(BaseModel):
    email: EmailStr


class FriendOut(BaseModel):
    """Un amigo ya aceptado, visto desde el usuario actual."""

    friendship_id: UUID
    user_id: UUID
    name: str
    email: str


class FriendRequestOut(BaseModel):
    """Solicitud de amistad pendiente recibida por el usuario actual."""

    id: UUID
    from_user_id: UUID
    from_name: str
    from_email: str
    created_at: datetime


# ----------------------------------------------------------- notificaciones


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: str
    title: str
    body: str
    data: Optional[dict] = None
    read_at: Optional[datetime] = None
    created_at: datetime


class UnreadCountOut(BaseModel):
    unread: int
