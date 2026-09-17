"""Rate limiting por IP con slowapi (en memoria, sin dependencias externas).

Frena la fuerza bruta contra el login y el martilleo automatizado de la API.
Los límites se leen de la configuración en cada petición, así que los tests
pueden desactivarlos sin reconstruir la app.
"""

from fastapi import HTTPException, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings


def _default_limit() -> str:
    # callable: se evalúa por petición, respetando el flag de config
    return settings.default_rate_limit if settings.rate_limit_enabled else "1000000/second"


def auth_limit() -> str:
    return settings.auth_rate_limit if settings.rate_limit_enabled else "1000000/second"


limiter = Limiter(key_func=get_remote_address, default_limits=[_default_limit])


def respuesta_frenada(espera_segundos: int) -> HTTPException:
    """La respuesta cuando una cuenta está frenada por fallos acumulados.

    Mismo cuerpo exista el email o no: el freno cuenta también los correos sin
    cuenta, así que este 429 no dice si alguien está registrado aquí. Lleva
    `Retry-After` para que la aplicación pueda decir cuánto falta sin que el
    mensaje lo detalle.
    """
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Demasiados intentos fallidos. Inténtalo de nuevo dentro de un rato.",
        headers={"Retry-After": str(espera_segundos)},
    )
