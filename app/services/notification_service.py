"""Creación de novedades para el centro de notificaciones dentro de la app."""

import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Notification


def notify(
    db: Session,
    user_id: uuid.UUID,
    *,
    type: str,
    title: str,
    body: str,
    data: Optional[dict] = None,
) -> Notification:
    """Añade una novedad para un usuario.

    No hace commit: lo hace quien llama, dentro de su propia transacción, para
    que la notificación y la acción que la origina se guarden juntas o nada.
    """
    notification = Notification(
        user_id=user_id, type=type, title=title, body=body, data=data
    )
    db.add(notification)
    return notification
