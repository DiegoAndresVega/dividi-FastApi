import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FriendshipStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"


class Friendship(Base):
    """Relación de amistad entre dos usuarios (solicitud + aceptación).

    `requester` envía la solicitud y `addressee` la acepta: mientras está
    `pending` es una solicitud pendiente; al aceptarla pasa a `accepted` y ya
    son amigos. Un par de usuarios solo puede tener una fila (constraint único).
    """

    __tablename__ = "friendships"
    __table_args__ = (
        UniqueConstraint("requester_id", "addressee_id", name="uq_friendship_pair"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    requester_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    addressee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[FriendshipStatus] = mapped_column(
        Enum(FriendshipStatus, native_enum=False, length=20),
        default=FriendshipStatus.pending,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    responded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    requester = relationship("User", foreign_keys=[requester_id])
    addressee = relationship("User", foreign_keys=[addressee_id])
