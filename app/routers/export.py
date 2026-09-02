import re
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, get_group_or_404, require_membership
from app.models import User
from app.services import export_service, recurring_service
from app.services.balance_service import compute_group_balances
from app.services.debt_simplifier import simplify_debts

router = APIRouter(prefix="/groups/{group_id}", tags=["export"])

NOMBRE_POR_DEFECTO = "grupo"


def _limpiar(nombre: str, solo_ascii: bool) -> str:
    """Deja el nombre del grupo en algo que pueda ir en un nombre de fichero."""
    flags = re.ASCII if solo_ascii else 0
    limpio = re.sub(r"[^\w\- ]", "", nombre, flags=flags).strip().replace(" ", "-")
    return limpio or NOMBRE_POR_DEFECTO


def _cabecera_de_descarga(nombre_del_grupo: str) -> str:
    """Content-Disposition con el nombre del grupo dentro.

    Las cabeceras HTTP viajan en latin-1, así que `filename` solo puede llevar
    ASCII: un grupo llamado «日本語» reventaba la respuesta entera al
    codificarla. `filename*` (RFC 6266) es el que miran los navegadores
    modernos y sí admite acentos y otros alfabetos; `filename` queda de
    respaldo para los que no lo entiendan.
    """
    ascii_ = _limpiar(nombre_del_grupo, solo_ascii=True)
    completo = _limpiar(nombre_del_grupo, solo_ascii=False)
    return (
        f'attachment; filename="dividi-{ascii_}.csv"; '
        f"filename*=UTF-8''{quote(f'dividi-{completo}.csv', safe='')}"
    )


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

    return Response(
        content=contenido,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": _cabecera_de_descarga(group.name)},
    )
