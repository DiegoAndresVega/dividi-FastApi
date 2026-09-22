from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.rate_limit import respuesta_frenada
from app.security_events import registrar
from app.schemas.user import AccountDelete, PasswordChange, UserOut, UserUpdate
from app.security import hash_password, verify_password
from app.services import (
    borrado_de_cuenta_service,
    datos_personales_service,
    login_attempt_service,
    refresh_token_service,
)

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=UserOut)
def get_me(user: User = Depends(get_current_user)):
    return user


@router.patch("", response_model=UserOut)
def update_me(
    payload: UserUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    for field, value in payload.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    request: Request,
    payload: PasswordChange,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Mismo marcador que el del login, porque es la misma contraseña la que se
    # está probando: con un token robado, este endpoint sería la puerta de al
    # lado para adivinarla sin que el freno del login se entere.
    espera = login_attempt_service.espera_restante(db, user.email)
    if espera:
        registrar("cambio_de_contrasena_frenado", request, user_id=user.id)
        raise respuesta_frenada(espera)

    if not verify_password(payload.current_password, user.hashed_password):
        espera = login_attempt_service.anotar_fallo(db, user.email)
        db.commit()
        registrar(
            "cambio_de_contrasena_fallido",
            request,
            user_id=user.id,
            espera_segundos=espera,
        )
        raise HTTPException(
            status_code=400, detail="La contraseña actual no es correcta"
        )
    login_attempt_service.olvidar(db, user.email)
    user.hashed_password = hash_password(payload.new_password)
    # La contraseña se cambia cuando se sospecha que alguien más entró, y su
    # refresh token seguiría valiendo un año. Se cierran todas las sesiones,
    # también la de este aparato, en la misma transacción que el hash: o se
    # guardan las dos cosas o ninguna.
    sesiones_cerradas = refresh_token_service.revocar_usuario(db, user.id)
    db.commit()
    registrar(
        "cambio_de_contrasena",
        request,
        user_id=user.id,
        sesiones_cerradas=sesiones_cerradas,
    )

@router.get("/export")
def export_my_data(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Copia de los datos personales de la cuenta (RGPD, artículos 15 y 20)."""
    registrar("export_de_datos_personales", request, user_id=user.id)
    return datos_personales_service.exportar(db, user)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(
    request: Request,
    payload: AccountDelete,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Borrado de la cuenta (RGPD, artículo 17).

    Se pide la contraseña por lo mismo que en el cambio de contraseña: con un
    token robado, este endpoint sería la forma más rápida de hacer daño.
    """
    espera = login_attempt_service.espera_restante(db, user.email)
    if espera:
        registrar("borrado_de_cuenta_frenado", request, user_id=user.id)
        raise respuesta_frenada(espera)

    if not verify_password(payload.password, user.hashed_password):
        espera = login_attempt_service.anotar_fallo(db, user.email)
        db.commit()
        registrar(
            "borrado_de_cuenta_fallido",
            request,
            user_id=user.id,
            espera_segundos=espera,
        )
        raise HTTPException(status_code=400, detail="La contraseña no es correcta")

    user_id = user.id
    borrado_de_cuenta_service.anonimizar(db, user)
    # Un solo commit: o se va todo (lo personal, los vínculos y la lápida) o no
    # se va nada. Una cuenta a medio borrar es peor que una sin borrar.
    db.commit()
    registrar("borrado_de_cuenta", request, user_id=user_id)
