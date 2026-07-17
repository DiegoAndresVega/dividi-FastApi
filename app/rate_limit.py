"""Rate limiting por IP con slowapi (en memoria, sin dependencias externas).

Frena la fuerza bruta contra el login y el martilleo automatizado de la API.
Los límites se leen de la configuración en cada petición, así que los tests
pueden desactivarlos sin reconstruir la app.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings


def _default_limit() -> str:
    # callable: se evalúa por petición, respetando el flag de config
    return settings.default_rate_limit if settings.rate_limit_enabled else "1000000/second"


def auth_limit() -> str:
    return settings.auth_rate_limit if settings.rate_limit_enabled else "1000000/second"


limiter = Limiter(key_func=get_remote_address, default_limits=[_default_limit])
