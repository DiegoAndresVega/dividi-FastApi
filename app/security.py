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
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    if jti is not None:
        payload["jti"] = str(jti)
    clave = settings.secret_key.get_secret_value()
    return jwt.encode(payload, clave, algorithm=settings.algorithm), expires_at


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


# Claims que el código da por hechos más adelante. Exigirlos aquí convierte un
# `None` inesperado a media petición en un 401 limpio en la puerta.
_CLAIMS_OBLIGATORIOS = ("exp", "iat", "sub", "type")


def decode_token(token: str, *, exigir_procedencia: bool = True) -> dict:
    """Decodifica y valida un JWT. Lanza jwt.PyJWTError si no vale.

    `exigir_procedencia=False` es para los refresh: los que hay en circulación
    duran un año y se emitieron sin `iss` ni `aud`, así que rechazarlos
    devolvería a todos los usuarios al login. Un refresh robado sigue frenado
    por su `jti`, que se comprueba contra la tabla `refresh_tokens` de esta
    base de datos. Lo que sí se exige: si los trae, que cuadren.
    """
    obligatorios = [*_CLAIMS_OBLIGATORIOS]
    if exigir_procedencia:
        obligatorios += ["iss", "aud"]

    datos = jwt.decode(
        token,
        settings.secret_key.get_secret_value(),
        # lista cerrada: sin esto, un token con `alg: none` o firmado con otro
        # algoritmo decidiría él mismo cómo se verifica
        algorithms=[settings.algorithm],
        issuer=settings.jwt_issuer if exigir_procedencia else None,
        audience=settings.jwt_audience if exigir_procedencia else None,
        options={"require": obligatorios, "verify_aud": exigir_procedencia},
    )
    if not exigir_procedencia:
        _comprobar_procedencia_si_viene(datos)
    return datos


def _comprobar_procedencia_si_viene(datos: dict) -> None:
    """Emisor y audiencia opcionales, pero no falseables.

    Un token sin `iss` ni `aud` es de antes del cambio y se acepta; uno que
    diga venir de otro sitio, no.
    """
    emisor = datos.get("iss")
    if emisor is not None and emisor != settings.jwt_issuer:
        raise jwt.InvalidIssuerError("El token dice venir de otro emisor")

    audiencia = datos.get("aud")
    if audiencia is None:
        return
    # `aud` puede ser una cadena o una lista, según quien lo firme
    valores = audiencia if isinstance(audiencia, list) else [audiencia]
    if settings.jwt_audience not in valores:
        raise jwt.InvalidAudienceError("El token no es para esta aplicación")
