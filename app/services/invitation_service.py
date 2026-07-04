"""Lógica de invitaciones de acceso a la plataforma (invite-only)."""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Invitation, User


class InviteError(ValueError):
    """El código de invitación no es válido, ya se usó o caducó."""


def generate_code() -> str:
    return secrets.token_urlsafe(16)


def is_first_user(db: Session) -> bool:
    """True si aún no hay ningún usuario (el fundador queda exento de invitación)."""
    return db.scalar(select(func.count()).select_from(User)) == 0


def create_invitation(
    db: Session,
    creator: User,
    email: Optional[str] = None,
    expires_in_days: Optional[int] = None,
) -> Invitation:
    expires_at = None
    days = expires_in_days if expires_in_days is not None else settings.invite_default_expire_days
    if days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=days)

    invitation = Invitation(
        code=generate_code(),
        created_by_id=creator.id,
        email=email.lower() if email else None,
        expires_at=expires_at,
    )
    db.add(invitation)
    return invitation


def validate_code(
    db: Session, code: str, email: Optional[str] = None
) -> Invitation:
    """Devuelve la invitación si el código es canjeable, o lanza InviteError."""
    invitation = db.scalar(select(Invitation).where(Invitation.code == code))
    if invitation is None:
        raise InviteError("El código de invitación no existe")
    if invitation.is_used:
        raise InviteError("Este código de invitación ya se ha utilizado")
    if invitation.is_expired():
        raise InviteError("El código de invitación ha caducado")
    if invitation.email and email and invitation.email != email.lower():
        raise InviteError("Este código está reservado para otro email")
    return invitation


def redeem(invitation: Invitation, user: User) -> None:
    invitation.used_by_id = user.id
    invitation.used_at = datetime.now(timezone.utc)


def build_link(invitation: Invitation) -> Optional[str]:
    base = settings.frontend_base_url
    if not base:
        return None
    return f"{base.rstrip('/')}/register?invite={invitation.code}"
