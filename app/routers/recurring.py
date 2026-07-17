import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user, get_group_or_404, require_membership
from app.models import MemberRole, RecurringExpense, SplitMethod, User
from app.schemas.recurring import RecurringCreate, RecurringOut, RecurringUpdate
from app.services import recurring_service

router = APIRouter(prefix="/groups/{group_id}/recurring", tags=["recurring"])


def _get_rule_or_404(db: Session, group_id: uuid.UUID, rule_id: uuid.UUID) -> RecurringExpense:
    rule = db.get(RecurringExpense, rule_id)
    if rule is None or rule.group_id != group_id:
        raise HTTPException(status_code=404, detail="Regla recurrente no encontrada")
    return rule


def _can_modify(membership, rule: RecurringExpense, user: User) -> None:
    if membership.role != MemberRole.admin and rule.created_by_id != user.id:
        raise HTTPException(
            status_code=403, detail="Solo puedes modificar tus propias reglas"
        )


@router.post("", response_model=RecurringOut, status_code=status.HTTP_201_CREATED)
def create_rule(
    group_id: uuid.UUID,
    payload: RecurringCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = get_group_or_404(db, group_id)
    require_membership(group, user)
    if not any(m.id == payload.paid_by for m in group.members):
        raise HTTPException(
            status_code=400, detail="'paid_by' debe ser un miembro del grupo"
        )
    # no se puede fechar una regla más atrás de lo que un solo request puede
    # recuperar de golpe: bloquea fechas absurdas (p.ej. "2000-01") que
    # inflarían la base de datos (anti-DoS), pero permite un backfill razonable
    if payload.start_period is not None:
        meses_atras = recurring_service.months_between(
            payload.start_period, recurring_service.current_period()
        )
        if meses_atras > settings.recurring_max_catchup_months:
            raise HTTPException(
                status_code=400,
                detail="La fecha de inicio está demasiado lejos en el pasado",
            )

    rule = RecurringExpense(
        group_id=group.id,
        description=payload.description,
        amount=payload.amount,
        category=payload.category,
        paid_by_id=payload.paid_by,
        split_method=SplitMethod(payload.split_method),
        created_by_id=user.id,
        day_of_month=payload.day_of_month,
        next_period=payload.start_period
        or recurring_service.default_start_period(payload.day_of_month),
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.get("", response_model=list[RecurringOut])
def list_rules(
    group_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = get_group_or_404(db, group_id)
    require_membership(group, user)
    return db.scalars(
        select(RecurringExpense)
        .where(RecurringExpense.group_id == group.id)
        .order_by(RecurringExpense.created_at)
    ).all()


@router.patch("/{rule_id}", response_model=RecurringOut)
def update_rule(
    group_id: uuid.UUID,
    rule_id: uuid.UUID,
    payload: RecurringUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = get_group_or_404(db, group_id)
    membership = require_membership(group, user)
    rule = _get_rule_or_404(db, group.id, rule_id)
    _can_modify(membership, rule, user)

    for field, value in payload.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(
    group_id: uuid.UUID,
    rule_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = get_group_or_404(db, group_id)
    membership = require_membership(group, user)
    rule = _get_rule_or_404(db, group.id, rule_id)
    _can_modify(membership, rule, user)
    db.delete(rule)
    db.commit()
