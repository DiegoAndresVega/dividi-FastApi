from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Invitation, User
from app.schemas.invitation import InvitationCheck, InvitationCreate, InvitationOut
from app.services import invitation_service

router = APIRouter(prefix="/invitations", tags=["invitations"])


def _to_out(invitation: Invitation) -> InvitationOut:
    out = InvitationOut.model_validate(invitation)
    out.invite_link = invitation_service.build_link(invitation)
    return out


@router.post("", response_model=InvitationOut, status_code=status.HTTP_201_CREATED)
def create_invitation(
    payload: InvitationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    invitation = invitation_service.create_invitation(
        db, user, email=payload.email, expires_in_days=payload.expires_in_days
    )
    db.commit()
    db.refresh(invitation)
    return _to_out(invitation)


@router.get("", response_model=list[InvitationOut])
def list_my_invitations(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    invitations = db.scalars(
        select(Invitation)
        .where(Invitation.created_by_id == user.id)
        .order_by(Invitation.created_at.desc())
    ).all()
    return [_to_out(i) for i in invitations]


@router.get("/{code}/check", response_model=InvitationCheck)
def check_invitation(code: str, db: Session = Depends(get_db)):
    """Endpoint público: valida un código antes de mostrar el formulario de registro."""
    try:
        invitation = invitation_service.validate_code(db, code)
    except invitation_service.InviteError as exc:
        return InvitationCheck(valid=False, reason=str(exc))
    return InvitationCheck(valid=True, email=invitation.email)


@router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invitation(
    invitation_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    invitation = db.get(Invitation, invitation_id)
    if invitation is None or invitation.created_by_id != user.id:
        raise HTTPException(status_code=404, detail="Invitación no encontrada")
    if invitation.is_used:
        raise HTTPException(
            status_code=400, detail="No se puede revocar una invitación ya utilizada"
        )
    db.delete(invitation)
    db.commit()
