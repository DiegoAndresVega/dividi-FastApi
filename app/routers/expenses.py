import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, get_group_or_404, require_membership
from app.models import (
    Expense,
    ExpenseCategory,
    ExpenseSplit,
    Group,
    GroupMember,
    MemberRole,
    SplitMethod,
    User,
)
from app.schemas.expense import ExpenseCreate, ExpenseOut, ExpenseUpdate, SplitInput
from app.services import recurring_service
from app.services.split_calculator import (
    SplitSpec,
    SplitValidationError,
    compute_splits,
)

router = APIRouter(prefix="/groups/{group_id}/expenses", tags=["expenses"])


def _check_currency(currency: Optional[str], group: Group) -> str:
    # MVP: un grupo opera en una única moneda
    if currency is not None and currency != group.default_currency:
        raise HTTPException(
            status_code=400,
            detail=f"El grupo opera en {group.default_currency}; multi-divisa no soportado",
        )
    return group.default_currency


def _check_paid_by(paid_by: uuid.UUID, group: Group) -> None:
    if not any(m.id == paid_by for m in group.members):
        raise HTTPException(
            status_code=400, detail="'paid_by' debe ser un miembro del grupo"
        )


def _build_specs(
    method: SplitMethod, splits: Optional[list[SplitInput]], group: Group
) -> list[SplitSpec]:
    """Construye las especificaciones de reparto. Sin `splits` explícitos:
    'equal' participa todo el grupo y 'percentage' usa los default_percentage."""
    if splits:
        member_ids = {m.id for m in group.members}
        specs = []
        for split in splits:
            if split.group_member_id not in member_ids:
                raise HTTPException(
                    status_code=400,
                    detail=f"El miembro {split.group_member_id} no pertenece al grupo",
                )
            specs.append(
                SplitSpec(
                    member_id=split.group_member_id,
                    percentage=split.percentage if method == SplitMethod.percentage else None,
                    exact_amount=split.exact_amount if method == SplitMethod.exact else None,
                    shares=split.shares if method == SplitMethod.shares else None,
                )
            )
        return specs

    if method == SplitMethod.equal:
        return [SplitSpec(member_id=m.id) for m in group.members]
    if method == SplitMethod.percentage:
        return [
            SplitSpec(member_id=m.id, percentage=m.default_percentage)
            for m in group.members
        ]
    raise HTTPException(
        status_code=400, detail=f"El método '{method.value}' requiere indicar 'splits'"
    )


def _replace_splits(expense: Expense, specs: list[SplitSpec], computed: list) -> None:
    spec_by_member = {s.member_id: s for s in specs}
    expense.splits.clear()
    for member_id, computed_amount in computed:
        spec = spec_by_member[member_id]
        expense.splits.append(
            ExpenseSplit(
                group_member_id=member_id,
                percentage=spec.percentage,
                exact_amount=spec.exact_amount,
                shares=spec.shares,
                computed_amount=computed_amount,
            )
        )


def _can_modify(membership: GroupMember, expense: Expense, user: User) -> None:
    # un admin puede editar/borrar cualquier gasto; un member solo los suyos
    if membership.role != MemberRole.admin and expense.created_by_id != user.id:
        raise HTTPException(
            status_code=403, detail="Solo puedes modificar tus propios gastos"
        )


def _get_expense_or_404(db: Session, group: Group, expense_id: uuid.UUID) -> Expense:
    expense = db.get(Expense, expense_id)
    if expense is None or expense.group_id != group.id:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    return expense


@router.post("", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
def create_expense(
    group_id: uuid.UUID,
    payload: ExpenseCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = get_group_or_404(db, group_id)
    require_membership(group, user)
    _check_paid_by(payload.paid_by, group)
    currency = _check_currency(payload.currency, group)

    specs = _build_specs(payload.split_method, payload.splits, group)
    try:
        computed = compute_splits(payload.amount, payload.split_method, specs)
    except SplitValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    expense = Expense(
        group_id=group.id,
        description=payload.description,
        amount=payload.amount,
        currency=currency,
        category=payload.category,
        paid_by_id=payload.paid_by,
        split_method=payload.split_method,
        created_by_id=user.id,
    )
    _replace_splits(expense, specs, computed)
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


@router.get("", response_model=list[ExpenseOut])
def list_expenses(
    group_id: uuid.UUID,
    category: Optional[ExpenseCategory] = Query(default=None),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = get_group_or_404(db, group_id)
    require_membership(group, user)
    # materializa los gastos recurrentes vencidos antes de listar
    recurring_service.materialize_due(db, group)

    stmt = select(Expense).where(Expense.group_id == group.id)
    if category is not None:
        stmt = stmt.where(Expense.category == category)
    if date_from is not None:
        stmt = stmt.where(Expense.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Expense.created_at <= date_to)
    return db.scalars(stmt.order_by(Expense.created_at.desc())).all()


@router.get("/{expense_id}", response_model=ExpenseOut)
def get_expense(
    group_id: uuid.UUID,
    expense_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = get_group_or_404(db, group_id)
    require_membership(group, user)
    return _get_expense_or_404(db, group, expense_id)


@router.patch("/{expense_id}", response_model=ExpenseOut)
def update_expense(
    group_id: uuid.UUID,
    expense_id: uuid.UUID,
    payload: ExpenseUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = get_group_or_404(db, group_id)
    membership = require_membership(group, user)
    expense = _get_expense_or_404(db, group, expense_id)
    _can_modify(membership, expense, user)

    if payload.description is not None:
        expense.description = payload.description
    if payload.category is not None:
        expense.category = payload.category
    if payload.currency is not None:
        expense.currency = _check_currency(payload.currency, group)
    if payload.paid_by is not None:
        _check_paid_by(payload.paid_by, group)
        expense.paid_by_id = payload.paid_by

    new_amount = payload.amount if payload.amount is not None else expense.amount
    new_method = (
        payload.split_method if payload.split_method is not None else expense.split_method
    )
    needs_recompute = (
        payload.amount is not None
        or payload.split_method is not None
        or payload.splits is not None
    )
    if needs_recompute:
        if payload.splits is not None:
            specs = _build_specs(new_method, payload.splits, group)
        else:
            # reutilizar la definición de reparto existente con el nuevo importe/método
            specs = [
                SplitSpec(
                    member_id=s.group_member_id,
                    percentage=s.percentage,
                    exact_amount=s.exact_amount,
                    shares=s.shares,
                )
                for s in expense.splits
            ]
        try:
            computed = compute_splits(new_amount, new_method, specs)
        except SplitValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        expense.amount = new_amount
        expense.split_method = new_method
        _replace_splits(expense, specs, computed)

    db.commit()
    db.refresh(expense)
    return expense


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(
    group_id: uuid.UUID,
    expense_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = get_group_or_404(db, group_id)
    membership = require_membership(group, user)
    expense = _get_expense_or_404(db, group, expense_id)
    _can_modify(membership, expense, user)

    db.delete(expense)
    db.commit()
