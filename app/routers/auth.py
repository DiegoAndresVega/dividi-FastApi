import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import GroupMember, RefreshToken, User
from app.rate_limit import auth_limit, limiter, respuesta_frenada
from app.schemas.user import RefreshRequest, Token, UserCreate, UserOut
from app.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.security_events import registrar
from app.services import invitation_service, login_attempt_service, refresh_token_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(auth_limit)
def register(request: Request, payload: UserCreate, db: Session = Depends(get_db)):
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Ya existe un usuario con ese email")

    # invite-only: salvo el primer usuario (fundador), hace falta un código válido
    invitation = None
    if settings.require_invite and not invitation_service.is_first_user(db):
        if not payload.invite_code:
            raise HTTPException(
                status_code=403, detail="Se requiere un código de invitación para registrarse"
            )
        try:
            invitation = invitation_service.validate_code(db, payload.invite_code, email)
        except invitation_service.InviteError as exc:
            raise HTTPException(status_code=403, detail=str(exc))

    user = User(email=email, name=payload.name, hashed_password=hash_password(payload.password))
    db.add(user)
    db.flush()

    if invitation is not None:
        invitation_service.redeem(invitation, user)

    # vincular invitaciones pendientes: memberships de grupo creadas con este
    # email antes de que el usuario tuviera cuenta
    pending = db.scalars(
        select(GroupMember).where(
            GroupMember.invited_email == email, GroupMember.user_id.is_(None)
        )
    ).all()
    for membership in pending:
        membership.user_id = user.id

    db.commit()
    db.refresh(user)
    registrar(
        "alta_de_usuario",
        request,
        user_id=user.id,
        por_invitacion=invitation is not None,
    )
    return user


@router.post("/login", response_model=Token)
@limiter.limit(auth_limit)
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    espera = login_attempt_service.espera_restante(db, form.username)
    if espera:
        # Antes de mirar la contraseña: mientras la cuenta está frenada no se
        # comprueba nada, ni siquiera si acertó. Si no, veinte IPs distintas
        # prueban veinte contraseñas sin que el límite por IP se entere.
        registrar("login_frenado", request, espera_segundos=espera)
        raise respuesta_frenada(espera)

    user = db.scalar(select(User).where(User.email == form.username.lower()))
    if user is None or not verify_password(form.password, user.hashed_password):
        # Sin el email: un registro de intentos fallidos con el email dentro es
        # una lista de correos válidos para quien llegue a leer los logs. El id
        # solo se pone cuando el usuario existe, que ya dice si el fallo fue de
        # contraseña o de cuenta inexistente. Se lee antes del commit, que
        # caduca el objeto y obligaría a volver a la base a por el mismo dato.
        user_id = user.id if user else None
        espera = login_attempt_service.anotar_fallo(db, form.username)
        # el fallo se guarda aunque la petición acabe en error: sin commit
        # explícito, la excepción se lleva por delante lo que acaba de contarse
        db.commit()
        registrar(
            "login_fallido",
            request,
            user_id=user_id,
            espera_segundos=espera,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    login_attempt_service.olvidar(db, form.username)
    # el login abre familia nueva; de paso se tiran las filas ya caducadas
    refresh_token_service.limpiar_caducados(db)
    login_attempt_service.limpiar_caducados(db)
    tokens = Token(
        access_token=create_access_token(user.id),
        refresh_token=refresh_token_service.emitir(db, user.id),
    )
    db.commit()
    registrar("login_correcto", request, user_id=user.id)
    return tokens


@router.post("/refresh", response_model=Token)
@limiter.limit(auth_limit)
def refresh(request: Request, payload: RefreshRequest, db: Session = Depends(get_db)):
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token inválido"
    )
    try:
        data = decode_token(payload.refresh_token, exigir_procedencia=False)
    except jwt.PyJWTError:
        raise invalid
    if data.get("type") != "refresh":
        raise invalid
    # Sin jti no hay forma de saber si el token sigue vivo. Los emitidos antes
    # de la revocación no lo llevan: se rechazan a propósito, porque aceptarlos
    # dejaría el agujero abierto el año que duran.
    try:
        jti = uuid.UUID(data.get("jti", ""))
    except (ValueError, TypeError):
        raise invalid

    try:
        user_id, nuevo_refresh = refresh_token_service.rotar(db, jti)
    except refresh_token_service.RefreshTokenReutilizado:
        # La única señal de robo que da el sistema: un token ya gastado que
        # reaparece. La sesión entera acaba de caerse y ambos vuelven al login.
        db.commit()
        registrar("refresh_token_reutilizado", request)
        raise invalid
    except refresh_token_service.RefreshTokenInvalido:
        db.commit()
        registrar("refresh_rechazado", request)
        raise invalid

    user = db.get(User, user_id)
    if user is None:
        db.rollback()
        raise invalid

    tokens = Token(access_token=create_access_token(user.id), refresh_token=nuevo_refresh)
    db.commit()
    registrar("refresh", request, user_id=user.id)
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(auth_limit)
def logout(request: Request, payload: RefreshRequest, db: Session = Depends(get_db)):
    """Cierra la sesión en el servidor, no solo en el dispositivo.

    Responde 204 siempre, valga el token o no: si distinguiera, serviría para
    averiguar qué tokens existen. Revoca la familia entera, que es lo que de
    verdad es una sesión.
    """
    try:
        data = decode_token(payload.refresh_token, exigir_procedencia=False)
        jti = uuid.UUID(data.get("jti", ""))
    except (jwt.PyJWTError, ValueError, TypeError):
        return None

    anotado = db.get(RefreshToken, jti)
    if anotado is not None:
        refresh_token_service.revocar_familia(db, anotado.family_id)
        db.commit()
        registrar("logout", request, user_id=anotado.user_id)
    return None
