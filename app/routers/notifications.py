from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Notification, User
from app.schemas.social import NotificationOut, UnreadCountOut

router = APIRouter(prefix="/notifications", tags=["notifications"])

# Tope de novedades que devuelve el listado (evita respuestas sin límite).
MAX_NOTIFICATIONS = 100


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return db.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(MAX_NOTIFICATIONS)
    ).all()


@router.get("/unread-count", response_model=UnreadCountOut)
def unread_count(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    total = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
    )
    return UnreadCountOut(unread=total or 0)


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
def mark_all_read(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc))
    )
    db.commit()


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(
    notification_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notificación no encontrada")
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
    db.commit()
