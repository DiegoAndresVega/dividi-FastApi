from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import (
    NOTIF_FRIEND_ACCEPTED,
    NOTIF_FRIEND_REQUEST,
    Friendship,
    FriendshipStatus,
    User,
)
from app.schemas.social import FriendOut, FriendRequestCreate, FriendRequestOut
from app.services import friend_service, notification_service

router = APIRouter(prefix="/friends", tags=["friends"])


@router.post("/requests", status_code=status.HTTP_201_CREATED)
def send_request(
    payload: FriendRequestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    target = db.scalar(select(User).where(User.email == payload.email.lower()))
    if target is None:
        raise HTTPException(
            status_code=404, detail="No hay ningún usuario con ese email en Dividi"
        )
    if target.id == user.id:
        raise HTTPException(
            status_code=400, detail="No puedes enviarte una solicitud a ti mismo"
        )

    existing = friend_service.existing_between(db, user.id, target.id)
    if existing is not None:
        if existing.status == FriendshipStatus.accepted:
            raise HTTPException(status_code=409, detail="Ya sois amigos")
        # ya hay una solicitud pendiente en algún sentido
        if existing.addressee_id == user.id:
            # esa persona ya me la había enviado: la aceptamos sin más (mutuo)
            existing.status = FriendshipStatus.accepted
            existing.responded_at = datetime.now(timezone.utc)
            notification_service.notify(
                db,
                existing.requester_id,
                type=NOTIF_FRIEND_ACCEPTED,
                title="Solicitud aceptada",
                body=f"{user.name} y tú ya sois amigos en Dividi",
                data={"user_id": str(user.id)},
            )
            db.commit()
            return {"status": "accepted"}
        raise HTTPException(
            status_code=409, detail="Ya has enviado una solicitud a esa persona"
        )

    friendship = Friendship(requester_id=user.id, addressee_id=target.id)
    db.add(friendship)
    notification_service.notify(
        db,
        target.id,
        type=NOTIF_FRIEND_REQUEST,
        title="Nueva solicitud de amistad",
        body=f"{user.name} quiere ser tu amigo en Dividi",
        data={"from_user_id": str(user.id), "from_name": user.name},
    )
    db.commit()
    return {"status": "pending"}


@router.get("", response_model=list[FriendOut])
def list_friends(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    rows = db.scalars(
        select(Friendship).where(
            Friendship.status == FriendshipStatus.accepted,
            or_(
                Friendship.requester_id == user.id,
                Friendship.addressee_id == user.id,
            ),
        )
    ).all()
    friends = []
    for row in rows:
        other = row.addressee if row.requester_id == user.id else row.requester
        friends.append(
            FriendOut(
                friendship_id=row.id,
                user_id=other.id,
                name=other.name,
                email=other.email,
            )
        )
    friends.sort(key=lambda f: f.name.lower())
    return friends


@router.get("/requests", response_model=list[FriendRequestOut])
def list_incoming_requests(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Solicitudes pendientes que ha recibido el usuario actual."""
    rows = db.scalars(
        select(Friendship)
        .where(
            Friendship.addressee_id == user.id,
            Friendship.status == FriendshipStatus.pending,
        )
        .order_by(Friendship.created_at.desc())
    ).all()
    return [
        FriendRequestOut(
            id=row.id,
            from_user_id=row.requester.id,
            from_name=row.requester.name,
            from_email=row.requester.email,
            created_at=row.created_at,
        )
        for row in rows
    ]


def _get_pending_or_404(db: Session, request_id: UUID) -> Friendship:
    friendship = db.get(Friendship, request_id)
    if friendship is None or friendship.status != FriendshipStatus.pending:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    return friendship


@router.post("/requests/{request_id}/accept", status_code=status.HTTP_200_OK)
def accept_request(
    request_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    friendship = _get_pending_or_404(db, request_id)
    if friendship.addressee_id != user.id:
        raise HTTPException(
            status_code=403, detail="Solo puedes aceptar solicitudes dirigidas a ti"
        )
    friendship.status = FriendshipStatus.accepted
    friendship.responded_at = datetime.now(timezone.utc)
    notification_service.notify(
        db,
        friendship.requester_id,
        type=NOTIF_FRIEND_ACCEPTED,
        title="Solicitud aceptada",
        body=f"{user.name} aceptó tu solicitud de amistad",
        data={"user_id": str(user.id)},
    )
    db.commit()
    return {"status": "accepted"}


@router.delete("/requests/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
def decline_or_cancel_request(
    request_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Rechaza (si eres el destinatario) o cancela (si la enviaste) una solicitud."""
    friendship = _get_pending_or_404(db, request_id)
    if user.id not in (friendship.requester_id, friendship.addressee_id):
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    db.delete(friendship)
    db.commit()


@router.delete("/{friendship_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_friend(
    friendship_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    friendship = db.get(Friendship, friendship_id)
    if friendship is None or user.id not in (
        friendship.requester_id,
        friendship.addressee_id,
    ):
        raise HTTPException(status_code=404, detail="Amistad no encontrada")
    db.delete(friendship)
    db.commit()
