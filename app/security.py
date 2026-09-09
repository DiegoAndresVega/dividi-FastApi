import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


@dataclass(frozen=True)
class IssuedRefreshToken:
    """Un refresh token recién firmado, con lo que hace falta para anotarlo.

    El `jti` y la caducidad se devuelven aparte porque quien lo emite tiene que
    guardarlos en la tabla `refresh_tokens`; volver a decodificar el JWT solo
    para sacarlos sería trabajo de más.
    """

    token: str
    jti: uuid.UUID
    expires_at: datetime


def _create_token(
    user_id: uuid.UUID,
    token_type: str,
    expires_delta: timedelta,
    jti: uuid.UUID | None = None,
) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = now + expires_delta
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "iat": now,
        "exp": expires_at,
    }
    if jti is not None:
        payload["jti"] = str(jti)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm), expires_at


def create_access_token(user_id: uuid.UUID) -> str:
    token, _ = _create_token(
        user_id, "access", timedelta(minutes=settings.access_token_expire_minutes)
    )
    return token


def create_refresh_token(user_id: uuid.UUID) -> IssuedRefreshToken:
    """Firma un refresh token con `jti`, el identificador que permite revocarlo."""
    jti = uuid.uuid4()
    token, expires_at = _create_token(
        user_id, "refresh", timedelta(days=settings.refresh_token_expire_days), jti=jti
    )
    return IssuedRefreshToken(token=token, jti=jti, expires_at=expires_at)


def decode_token(token: str) -> dict:
    """Decodifica y valida un JWT. Lanza jwt.PyJWTError si es inválido o expiró."""
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
