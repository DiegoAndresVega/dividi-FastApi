import re
import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, get_group_or_404, require_membership
from app.models import User
from app.services import export_service, recurring_service
from app.services.balance_service import compute_group_balances
from app.services.debt_simplifier import simplify_debts

router = APIRouter(prefix="/groups/{group_id}", tags=["export"])


@router.get("/export")
def export_group_csv(
    group_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Resumen completo del grupo en CSV: gastos (con la parte de cada
    miembro), pagos, balances y settle-up sugerido."""
    group = get_group_or_404(db, group_id)
    require_membership(group, user)
    recurring_service.materialize_due(db, group)

    balances = compute_group_balances(group)
    settlements = simplify_debts(balances)
    contenido = export_service.build_csv(group, balances, settlements)

    nombre = re.sub(r"[^\w\- ]", "", group.name).strip().replace(" ", "-") or "grupo"
    return Response(
        content=contenido,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="dividi-{nombre}.csv"'
        },
    )
