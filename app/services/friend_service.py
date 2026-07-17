"""Consultas de amistad reutilizables entre routers."""

import uuid
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import Friendship, FriendshipStatus


def _pair(user_a: uuid.UUID, user_b: uuid.UUID):
    """Condición que casa la fila de amistad entre dos usuarios en cualquier
    sentido (da igual quién envió la solicitud)."""
    return or_(
        and_(
            Friendship.requester_id == user_a,
            Friendship.addressee_id == user_b,
        ),
        and_(
            Friendship.requester_id == user_b,
            Friendship.addressee_id == user_a,
        ),
    )


def existing_between(
    db: Session, user_a: uuid.UUID, user_b: uuid.UUID
) -> Optional[Friendship]:
    """La relación (pendiente o aceptada) entre dos usuarios, si existe."""
    return db.scalar(select(Friendship).where(_pair(user_a, user_b)))


def are_friends(db: Session, user_a: uuid.UUID, user_b: uuid.UUID) -> bool:
    """True solo si hay una amistad ya aceptada entre ambos."""
    return (
        db.scalar(
            select(Friendship).where(
                Friendship.status == FriendshipStatus.accepted,
                _pair(user_a, user_b),
            )
        )
        is not None
    )
