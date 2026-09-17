from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LoginAttempt(Base):
    """Fallos acumulados contra una cuenta, para poder frenarla.

    El límite por IP no cubre a quien dispone de muchas direcciones: veinte
    peticiones desde veinte IPs no lo rozan, y son veinte contraseñas probadas
    contra el mismo email. Esta tabla cuenta por cuenta, venga de donde venga.

    La clave es la huella del email, no el email: aquí acaba también todo
    correo que alguien teclee sin tener cuenta, y eso son datos de terceros que
    este servicio no tiene por qué guardar. Para contar fallos basta con poder
    reconocer que se trata del mismo.
    """

    __tablename__ = "login_attempts"

    email_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    fallos: Mapped[int] = mapped_column(Integer, default=0)
    # indexado porque la poda de filas viejas barre por él en cada login correcto
    ultimo_fallo_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, default=lambda: datetime.now(timezone.utc)
    )
    # nulo mientras quedan intentos por debajo del umbral
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
