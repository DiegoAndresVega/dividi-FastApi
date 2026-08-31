# Dividi — API de gastos compartidos.
# Autor: Diego Andres Vega Silva.
from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.middleware import MaxBodySizeMiddleware, SecurityHeadersMiddleware
from app.rate_limit import limiter
from app.routers import (
    auth,
    expenses,
    export,
    friends,
    groups,
    invitations,
    me,
    notifications,
    payments,
    personal,
    receipts,
    recurring,
    savings,
)

ROUTERS = (
    auth,
    me,
    personal,
    invitations,
    groups,
    expenses,
    recurring,
    receipts,
    export,
    payments,
    savings,
    friends,
    notifications,
)


def _opciones_de_documentacion() -> dict:
    """En producción no se publica el esquema de la API.

    /docs, /redoc y /openapi.json describen todas las rutas, todos los campos de
    cada modelo y todos los códigos de error. En desarrollo es útil; servido a
    internet es un mapa de la superficie de la API.
    """
    if settings.es_desarrollo:
        return {}
    return {"docs_url": None, "redoc_url": None, "openapi_url": None}


def crear_app() -> FastAPI:
    app = FastAPI(
        title="Dividi",
        version="1.0.0",
        description=(
            "Dividi — API de gastos compartidos (tipo Tricount/Splitwise): grupos, gastos "
            "con 4 métodos de división, balances netos y simplificación de deudas. "
            "Registro por invitación."
        ),
        **_opciones_de_documentacion(),
    )

    # --- Endurecimiento ---
    # Rate limiting por IP (slowapi): frena fuerza bruta y martilleo.
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    # Rechaza cuerpos gigantes antes de leerlos; añade cabeceras de seguridad.
    app.add_middleware(MaxBodySizeMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    for router in ROUTERS:
        app.include_router(router.router)

    @app.get("/health", tags=["health"])
    def health():
        return {"status": "ok"}

    return app


app = crear_app()
