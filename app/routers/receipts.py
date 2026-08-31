import io
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
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

# Formatos que aceptamos, tal y como los nombra Pillow, y la extensión con la
# que se guardan. La clave es el formato REAL del fichero, no lo que declare
# quien lo sube: la cabecera Content-Type la pone el cliente y no vale de nada.
FORMATOS_ACEPTADOS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
_MEDIA_BY_EXT = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}

MAX_RECEIPT_BYTES = 5 * 1024 * 1024
# Tope de píxeles al descomprimir. Un PNG de pocos kilobytes puede convertirse
# en cientos de megas en memoria; se comprueba antes de tocar los píxeles.
MAX_RECEIPT_PIXELS = 40_000_000


def _receipts_dir() -> Path:
    path = Path(settings.receipts_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _rechazo_por_contenido() -> HTTPException:
    return HTTPException(
        status_code=415, detail="El tique debe ser una imagen (JPG, PNG o WebP)"
    )


def _reprocesar_imagen(data: bytes) -> tuple[bytes, str]:
    """Reabre la imagen y la vuelve a escribir desde sus píxeles.

    Hace dos cosas de una vez. Lo que no sea una imagen de verdad no se puede
    abrir y se rechaza, por mucho que el Content-Type diga otra cosa. Y al
    reescribirla se pierden los metadatos EXIF, que en una foto de móvil llevan
    las coordenadas GPS del sitio donde se hizo.

    Devuelve los bytes ya limpios y la extensión que les corresponde.
    """
    try:
        with Image.open(io.BytesIO(data)) as original:
            formato = original.format
            if formato not in FORMATOS_ACEPTADOS:
                raise _rechazo_por_contenido()
            if original.width * original.height > MAX_RECEIPT_PIXELS:
                raise HTTPException(
                    status_code=413,
                    detail="La imagen tiene demasiados píxeles",
                )
            # Aplica la orientación guardada en el EXIF ANTES de tirarlo: si no,
            # las fotos hechas en vertical se guardarían tumbadas.
            enderezada = ImageOps.exif_transpose(original)
            limpia = enderezada.copy()
            limpia.info = {}
    except HTTPException:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        raise _rechazo_por_contenido()

    salida = io.BytesIO()
    extras = {"quality": 90} if formato == "JPEG" else {}
    limpia.save(salida, format=formato, **extras)
    return salida.getvalue(), FORMATOS_ACEPTADOS[formato]


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

    # Nada se escribe en disco hasta que el contenido demuestra ser una imagen.
    limpia, extension = _reprocesar_imagen(data)

    anterior = _find_file(expense_id)
    if anterior is not None:
        anterior.unlink()
    (_receipts_dir() / f"{expense_id}{extension}").write_bytes(limpia)

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
