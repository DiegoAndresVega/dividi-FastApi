import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# Tipos de novedad. Se guardan como texto (no enum nativo) para poder añadir
# más adelante sin necesidad de migrar la base de datos.
NOTIF_FRIEND_REQUEST = "friend_request"
NOTIF_FRIEND_ACCEPTED = "friend_accepted"
NOTIF_ADDED_TO_GROUP = "added_to_group"


class Notification(Base):
    """Novedad para un usuario (centro de notificaciones dentro de la app).

    Sin push: la app las consulta al abrirse y muestra un aviso local si hay
    nuevas. `data` guarda el contexto (p. ej. `group_id`) para poder navegar
    al tocarla.
    """

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(String(500))
    data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
