import uuid
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    get_current_user,
    get_group_or_404,
    require_admin,
    require_membership,
)
from app.models import (
    Expense,
    ExpenseSplit,
    Group,
    GroupMember,
    MemberRole,
    Payment,
    User,
)
from app.schemas.group import (
    BalanceOut,
    GroupCreate,
    GroupOut,
    GroupUpdate,
    MemberAdd,
    MemberOut,
    MemberRemove,
    MemberUpdate,
    SettlementOut,
)
from app.services.balance_service import compute_group_balances
from app.services.debt_simplifier import simplify_debts

router = APIRouter(prefix="/groups", tags=["groups"])

HUNDRED = Decimal("100")


def _validate_group_percentages(group: Group) -> None:
    total = sum((m.default_percentage or Decimal("0")) for m in group.members)
    if total != HUNDRED:
        raise HTTPException(
            status_code=400,
            detail=f"Los porcentajes del grupo deben sumar 100 (suma actual: {total})",
        )


def _apply_rebalance(group: Group, rebalance: Optional[dict]) -> None:
    if not rebalance:
        return
    members_by_id = {m.id: m for m in group.members}
    for member_id, percentage in rebalance.items():
        member = members_by_id.get(member_id)
        if member is None:
            raise HTTPException(
                status_code=400,
                detail=f"El miembro {member_id} no pertenece al grupo",
            )
        member.default_percentage = percentage


def _get_member_or_404(group: Group, member_id: uuid.UUID) -> GroupMember:
    member = next((m for m in group.members if m.id == member_id), None)
    if member is None:
        raise HTTPException(status_code=404, detail="Miembro no encontrado en el grupo")
    return member


@router.post("", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
def create_group(
    payload: GroupCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = Group(name=payload.name, owner_id=user.id, default_currency=payload.default_currency)
    group.members.append(
        GroupMember(
            user_id=user.id,
            display_name=user.name,
            default_percentage=HUNDRED,
            role=MemberRole.admin,
        )
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


@router.get("", response_model=list[GroupOut])
def list_groups(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(
        select(Group).join(GroupMember).where(GroupMember.user_id == user.id)
    ).all()


@router.get("/{group_id}", response_model=GroupOut)
def get_group(
    group_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = get_group_or_404(db, group_id)
    require_membership(group, user)
    return group


@router.patch("/{group_id}", response_model=GroupOut)
def update_group(
    group_id: uuid.UUID,
    payload: GroupUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = get_group_or_404(db, group_id)
    require_admin(require_membership(group, user))

    if payload.name is not None:
        group.name = payload.name
    if payload.default_currency is not None:
        group.default_currency = payload.default_currency
    db.commit()
    db.refresh(group)
    return group


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    group_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = get_group_or_404(db, group_id)
    require_admin(require_membership(group, user))
    db.delete(group)
    db.commit()


@router.post(
    "/{group_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED
)
def add_member(
    group_id: uuid.UUID,
    payload: MemberAdd,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = get_group_or_404(db, group_id)
    require_admin(require_membership(group, user))

    linked_user = None
    if payload.email:
        email = payload.email.lower()
        for member in group.members:
            if member.invited_email == email or (member.user and member.user.email == email):
                raise HTTPException(
                    status_code=409, detail="Ya existe un miembro con ese email en el grupo"
                )
        linked_user = db.scalar(select(User).where(User.email == email))

    display_name = payload.display_name or (
        linked_user.name if linked_user else payload.email.split("@")[0]
    )
    member = GroupMember(
        user_id=linked_user.id if linked_user else None,
        invited_email=None if linked_user else (payload.email.lower() if payload.email else None),
        display_name=display_name,
        default_percentage=payload.default_percentage,
        role=MemberRole.member,
    )
    group.members.append(member)
    _apply_rebalance(group, payload.rebalance)
    _validate_group_percentages(group)

    db.commit()
    db.refresh(member)
    return member


@router.patch("/{group_id}/members/{member_id}", response_model=MemberOut)
def update_member(
    group_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: MemberUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = get_group_or_404(db, group_id)
    require_admin(require_membership(group, user))
    member = _get_member_or_404(group, member_id)

    if payload.display_name is not None:
        member.display_name = payload.display_name
    if payload.role is not None:
        other_admins = any(
            m.role == MemberRole.admin and m.id != member.id for m in group.members
        )
        if payload.role == MemberRole.member and member.role == MemberRole.admin and not other_admins:
            raise HTTPException(
                status_code=400, detail="El grupo debe tener al menos un administrador"
            )
        member.role = payload.role
    if payload.default_percentage is not None:
        member.default_percentage = payload.default_percentage
    _apply_rebalance(group, payload.rebalance)

    if payload.default_percentage is not None or payload.rebalance:
        _validate_group_percentages(group)

    db.commit()
    db.refresh(member)
    return member


@router.delete("/{group_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    group_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: Optional[MemberRemove] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = get_group_or_404(db, group_id)
    require_admin(require_membership(group, user))
    member = _get_member_or_404(group, member_id)

    has_activity = db.scalar(
        select(
            exists().where(Expense.paid_by_id == member.id)
            | exists().where(ExpenseSplit.group_member_id == member.id)
            | exists().where(Payment.from_member_id == member.id)
            | exists().where(Payment.to_member_id == member.id)
        )
    )
    if has_activity:
        raise HTTPException(
            status_code=400,
            detail="No se puede eliminar un miembro con gastos o pagos asociados",
        )
    if member.role == MemberRole.admin and not any(
        m.role == MemberRole.admin and m.id != member.id for m in group.members
    ) and len(group.members) > 1:
        raise HTTPException(
            status_code=400, detail="El grupo debe tener al menos un administrador"
        )

    group.members.remove(member)
    _apply_rebalance(group, payload.rebalance if payload else None)
    if group.members:
        _validate_group_percentages(group)
    db.commit()


@router.get("/{group_id}/balances", response_model=list[BalanceOut])
def get_balances(
    group_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = get_group_or_404(db, group_id)
    require_membership(group, user)

    balances = compute_group_balances(group)
    return [
        BalanceOut(member_id=m.id, display_name=m.display_name, balance=balances[m.id])
        for m in group.members
    ]


@router.get("/{group_id}/settle-up", response_model=list[SettlementOut])
def settle_up(
    group_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = get_group_or_404(db, group_id)
    require_membership(group, user)

    balances = compute_group_balances(group)
    settlements = simplify_debts(balances)
    names = {m.id: m.display_name for m in group.members}
    return [
        SettlementOut(
            from_member_id=s.from_member_id,
            from_display_name=names[s.from_member_id],
            to_member_id=s.to_member_id,
            to_display_name=names[s.to_member_id],
            amount=s.amount,
        )
        for s in settlements
    ]
