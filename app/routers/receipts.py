import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user, get_group_or_404, require_membership
from app.models import User
from app.routers.expenses import _can_modify, _get_expense_or_404
from app.schemas.expense import ExpenseOut

router = APIRouter(
    prefix="/groups/{group_id}/expenses/{expense_id}/receipt", tags=["receipts"]
)

# tipos de imagen que aceptamos y su extensión en disco
_ALLOWED = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
_MEDIA_BY_EXT = {ext: media for media, ext in _ALLOWED.items()}
MAX_RECEIPT_BYTES = 5 * 1024 * 1024


def _receipts_dir() -> Path:
    path = Path(settings.receipts_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _find_file(expense_id: uuid.UUID) -> Path | None:
    for candidate in _receipts_dir().glob(f"{expense_id}.*"):
        return candidate
    return None


@router.post("", response_model=ExpenseOut)
async def upload_receipt(
    group_id: uuid.UUID,
    expense_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = get_group_or_404(db, group_id)
    membership = require_membership(group, user)
    expense = _get_expense_or_404(db, group, expense_id)
    _can_modify(membership, expense, user)

    extension = _ALLOWED.get(file.content_type or "")
    if extension is None:
        raise HTTPException(
            status_code=415, detail="El tique debe ser una imagen (JPG, PNG o WebP)"
        )
    # lee por trozos y aborta en cuanto se pasa del límite: nunca cargamos
    # en memoria un archivo mayor de lo permitido, venga como venga
    data = b""
    while chunk := await file.read(64 * 1024):
        data += chunk
        if len(data) > MAX_RECEIPT_BYTES:
            raise HTTPException(
                status_code=413, detail="La imagen no puede superar los 5 MB"
            )
    if not data:
        raise HTTPException(status_code=400, detail="El archivo llegó vacío")

    anterior = _find_file(expense_id)
    if anterior is not None:
        anterior.unlink()
    (_receipts_dir() / f"{expense_id}{extension}").write_bytes(data)

    expense.receipt_image_url = f"/groups/{group_id}/expenses/{expense_id}/receipt"
    db.commit()
    db.refresh(expense)
    return expense


@router.get("")
def get_receipt(
    group_id: uuid.UUID,
    expense_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = get_group_or_404(db, group_id)
    require_membership(group, user)
    _get_expense_or_404(db, group, expense_id)

    archivo = _find_file(expense_id)
    if archivo is None:
        raise HTTPException(status_code=404, detail="Este gasto no tiene tique")
    return FileResponse(archivo, media_type=_MEDIA_BY_EXT[archivo.suffix])


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_receipt(
    group_id: uuid.UUID,
    expense_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = get_group_or_404(db, group_id)
    membership = require_membership(group, user)
    expense = _get_expense_or_404(db, group, expense_id)
    _can_modify(membership, expense, user)

    archivo = _find_file(expense_id)
    if archivo is not None:
        archivo.unlink()
    expense.receipt_image_url = None
    db.commit()
