from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

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

app = FastAPI(
    title="Dividi",
    version="1.0.0",
    description=(
        "Dividi — API de gastos compartidos (tipo Tricount/Splitwise): grupos, gastos "
        "con 4 métodos de división, balances netos y simplificación de deudas. "
        "Registro por invitación."
    ),
)

# --- Endurecimiento ---
# Rate limiting por IP (slowapi): frena fuerza bruta y martilleo.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
# Rechaza cuerpos gigantes antes de leerlos; añade cabeceras de seguridad.
app.add_middleware(MaxBodySizeMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(auth.router)
app.include_router(me.router)
app.include_router(personal.router)
app.include_router(invitations.router)
app.include_router(groups.router)
app.include_router(expenses.router)
app.include_router(recurring.router)
app.include_router(receipts.router)
app.include_router(export.router)
app.include_router(payments.router)
app.include_router(savings.router)
app.include_router(friends.router)
app.include_router(notifications.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
