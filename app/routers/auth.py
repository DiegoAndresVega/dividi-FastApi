import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import GroupMember, RefreshToken, User
from app.rate_limit import auth_limit, limiter
from app.schemas.user import RefreshRequest, Token, UserCreate, UserOut
from app.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.services import invitation_service, refresh_token_service

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
    return user


@router.post("/login", response_model=Token)
@limiter.limit(auth_limit)
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.email == form.username.lower()))
    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # el login abre familia nueva; de paso se tiran las filas ya caducadas
    refresh_token_service.limpiar_caducados(db)
    tokens = Token(
        access_token=create_access_token(user.id),
        refresh_token=refresh_token_service.emitir(db, user.id),
    )
    db.commit()
    return tokens


@router.post("/refresh", response_model=Token)
@limiter.limit(auth_limit)
def refresh(request: Request, payload: RefreshRequest, db: Session = Depends(get_db)):
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token inválido"
    )
    try:
        data = decode_token(payload.refresh_token)
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
    except refresh_token_service.RefreshTokenInvalido:
        # la rotación puede haber revocado la familia al detectar una copia,
        # y eso hay que guardarlo aunque la petición acabe en 401
        db.commit()
        raise invalid

    user = db.get(User, user_id)
    if user is None:
        db.rollback()
        raise invalid

    tokens = Token(access_token=create_access_token(user.id), refresh_token=nuevo_refresh)
    db.commit()
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
        data = decode_token(payload.refresh_token)
        jti = uuid.UUID(data.get("jti", ""))
    except (jwt.PyJWTError, ValueError, TypeError):
        return None

    anotado = db.get(RefreshToken, jti)
    if anotado is not None:
        refresh_token_service.revocar_familia(db, anotado.family_id)
        db.commit()
    return None
