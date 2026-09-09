import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RefreshToken(Base):
    """Un refresh token emitido, para poder dejar de aceptarlo.

    El JWT sigue siendo autocontenido; esta tabla solo dice cuáles siguen
    vivos. Sin ella un token robado vale el año entero que dura, aunque el
    dueño siga usando la aplicación.

    `family_id` agrupa la cadena de rotaciones que nace en un login. Cuando un
    token ya gastado vuelve a aparecer es que alguien tiene una copia, y no hay
    forma de saber si el que la tiene es el dueño o el ladrón: se cae la
    familia entera y ambos vuelven al login.
    """

    __tablename__ = "refresh_tokens"

    # el jti del JWT: la clave primaria natural, no hace falta otro id
    jti: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # sellos en vez de banderas: además de saber que ya no vale, queda cuándo
    # dejó de valer, que es lo que se mira cuando hay que investigar algo
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    @property
    def is_usable(self) -> bool:
        if self.used_at is not None or self.revoked_at is not None:
            return False
        return _en_utc(self.expires_at) > datetime.now(timezone.utc)


def _en_utc(momento: datetime) -> datetime:
    """Devuelve el instante con zona horaria.

    Postgres guarda y devuelve la zona, pero SQLite —el motor de los tests— la
    pierde por el camino y devuelve una fecha ingenua. Compararla con una que
    sí la lleva revienta, así que se asume UTC, que es lo único que escribimos.
    """
    if momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento
