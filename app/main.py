from fastapi import FastAPI

from app.routers import (
    auth,
    expenses,
    export,
    groups,
    invitations,
    me,
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


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
