"""Middlewares de endurecimiento: límite de tamaño de petición y cabeceras
de seguridad. Ambos son baratos y estándar en APIs de producción."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings

_SECURITY_HEADERS = {
    # el navegador no debe adivinar el tipo de contenido
    "X-Content-Type-Options": "nosniff",
    # la API no se embebe en iframes de terceros (clickjacking)
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    # sin recursos externos: la API solo devuelve datos e imágenes propias
    "Content-Security-Policy": "default-src 'none'; img-src 'self'",
    # la API no necesita ninguna capacidad del navegador: se niegan todas
    "Permissions-Policy": (
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
        "magnetometer=(), microphone=(), payment=(), usb=()"
    ),
}

# Un año, el mínimo que piden las guías para que la cabecera sirva de algo.
# Sin 'preload': entrar en la lista que llevan los navegadores dentro no se
# deshace en meses, y no compensa para un dominio con una sola aplicación.
_HSTS = "max-age=31536000; includeSubDomains"


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    """Rechaza cuerpos por encima del límite ANTES de leerlos en memoria.

    Mira el Content-Length declarado; evita que una subida enorme (p. ej. un
    'tique' de 2 GB) agote la memoria del contenedor.
    """

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > settings.max_request_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "La petición es demasiado grande"},
                    )
            except ValueError:
                return JSONResponse(
                    status_code=400, content={"detail": "Content-Length inválido"}
                )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        # HSTS solo en producción: la RFC 6797 prohíbe mandarla por HTTP, y en
        # local la API va por http://localhost. Enviarla ahí dejaría el
        # navegador del desarrollador forzando https a localhost durante un año.
        if not settings.es_desarrollo:
            response.headers.setdefault("Strict-Transport-Security", _HSTS)
        return response
