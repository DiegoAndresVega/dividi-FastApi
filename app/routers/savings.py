import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import SavingsEntry, SavingsEntryKind, SavingsPlan, User
from app.schemas.savings import (
    SavingsEntryCreate,
    SavingsPlanCreate,
    SavingsPlanDetail,
    SavingsPlanOut,
    SavingsPlanUpdate,
)
from app.services import savings_service
from app.services.savings_service import SavingsValidationError

router = APIRouter(prefix="/savings-plans", tags=["savings"])


def _get_plan_or_404(db: Session, plan_id: uuid.UUID, user: User) -> SavingsPlan:
    plan = db.get(SavingsPlan, plan_id)
    if plan is None or plan.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan de ahorro no encontrado")
    return plan


def _to_out(plan: SavingsPlan, detail: bool = False) -> dict:
    period = savings_service.current_period()
    saved = plan.saved_amount
    data = {
        "id": plan.id,
        "name": plan.name,
        "target_amount": plan.target_amount,
        "monthly_amount": plan.monthly_amount,
        "saved_amount": saved,
        "remaining_amount": savings_service.remaining_amount(plan),
        "months_to_goal": savings_service.months_to_goal(plan),
        "projected_period": savings_service.projected_period(plan),
        "current_period": period,
        "is_current_period_confirmed": savings_service.is_period_confirmed(
            plan, period
        ),
        "is_completed": saved >= plan.target_amount,
        "created_at": plan.created_at,
    }
    if detail:
        data["entries"] = plan.entries
    return data


@router.post("", response_model=SavingsPlanOut, status_code=status.HTTP_201_CREATED)
def create_plan(
    payload: SavingsPlanCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    plan = SavingsPlan(
        user_id=user.id,
        name=payload.name,
        target_amount=payload.target_amount,
        monthly_amount=payload.monthly_amount,
    )
    if payload.saved_amount > 0:
        # hucha inicial: dinero que ya estaba apartado antes del plan
        plan.entries.append(
            SavingsEntry(kind=SavingsEntryKind.adjustment, amount=payload.saved_amount)
        )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _to_out(plan)


@router.get("", response_model=list[SavingsPlanOut])
def list_plans(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    plans = db.scalars(
        select(SavingsPlan)
        .where(SavingsPlan.user_id == user.id)
        .order_by(SavingsPlan.created_at)
    ).all()
    return [_to_out(plan) for plan in plans]


@router.get("/{plan_id}", response_model=SavingsPlanDetail)
def get_plan(
    plan_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _to_out(_get_plan_or_404(db, plan_id, user), detail=True)


@router.patch("/{plan_id}", response_model=SavingsPlanOut)
def update_plan(
    plan_id: uuid.UUID,
    payload: SavingsPlanUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    plan = _get_plan_or_404(db, plan_id, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(plan, field, value)
    db.commit()
    db.refresh(plan)
    return _to_out(plan)


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan(
    plan_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    plan = _get_plan_or_404(db, plan_id, user)
    db.delete(plan)
    db.commit()


@router.post(
    "/{plan_id}/entries",
    response_model=SavingsPlanDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_entry(
    plan_id: uuid.UUID,
    payload: SavingsEntryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    plan = _get_plan_or_404(db, plan_id, user)

    if payload.kind == SavingsEntryKind.monthly:
        period = payload.period or savings_service.current_period()
    else:
        period = None  # los ajustes no cierran ningún mes

    try:
        savings_service.validate_entry(plan, payload.kind, payload.amount, period)
    except SavingsValidationError as error:
        raise HTTPException(status_code=400, detail=str(error))

    plan.entries.append(
        SavingsEntry(kind=payload.kind, amount=payload.amount, period=period)
    )
    db.commit()
    db.refresh(plan)
    return _to_out(plan, detail=True)
