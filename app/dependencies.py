import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Group, GroupMember, MemberRole, User
from app.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales inválidas",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        raise credentials_error
    if payload.get("type") != "access":
        raise credentials_error
    try:
        user_id = uuid.UUID(payload.get("sub", ""))
    except ValueError:
        raise credentials_error

    user = db.get(User, user_id)
    if user is None:
        raise credentials_error
    return user


def get_group_or_404(db: Session, group_id: uuid.UUID) -> Group:
    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    return group


def require_membership(group: Group, user: User) -> GroupMember:
    membership = next((m for m in group.members if m.user_id == user.id), None)
    if membership is None:
        raise HTTPException(status_code=403, detail="No eres miembro de este grupo")
    return membership


def require_admin(membership: GroupMember) -> None:
    if membership.role != MemberRole.admin:
        raise HTTPException(
            status_code=403, detail="Esta operación requiere rol de administrador"
        )
