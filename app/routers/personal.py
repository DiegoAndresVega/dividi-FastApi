import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import (
    PersonalExpense,
    User,
    UserBudget,
    UserFinance,
)
from app.models.expense import CATEGORY_MAX_LENGTH
from app.schemas.personal import (
    FinancesOut,
    FinancesUpdate,
    MonthlySummaryOut,
    PersonalExpenseCreate,
    PersonalExpenseOut,
    PersonalExpenseUpdate,
)
from app.services import personal_service

router = APIRouter(prefix="/me", tags=["mi-dinero"])


def _get_personal_or_404(
    db: Session, expense_id: uuid.UUID, user: User
) -> PersonalExpense:
    expense = db.get(PersonalExpense, expense_id)
    if expense is None or expense.user_id != user.id:
        raise HTTPException(status_code=404, detail="Gasto personal no encontrado")
    return expense


# ------------------------------------------------------- gastos personales


@router.post(
    "/expenses", response_model=PersonalExpenseOut, status_code=status.HTTP_201_CREATED
)
def create_personal_expense(
    payload: PersonalExpenseCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    expense = PersonalExpense(
        user_id=user.id,
        description=payload.description,
        amount=payload.amount,
        category=payload.category,
        category_icon=payload.category_icon,
    )
    if payload.created_at is not None:
        expense.created_at = payload.created_at
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


@router.get("/expenses", response_model=list[PersonalExpenseOut])
def list_personal_expenses(
    category: Optional[str] = Query(default=None, max_length=CATEGORY_MAX_LENGTH),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(PersonalExpense).where(PersonalExpense.user_id == user.id)
    if category is not None:
        # misma normalización que al guardar: «Agua» encuentra «agua»
        stmt = stmt.where(PersonalExpense.category == category.strip().lower())
    if date_from is not None:
        stmt = stmt.where(PersonalExpense.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(PersonalExpense.created_at <= date_to)
    return db.scalars(stmt.order_by(PersonalExpense.created_at.desc())).all()


@router.patch("/expenses/{expense_id}", response_model=PersonalExpenseOut)
def update_personal_expense(
    expense_id: uuid.UUID,
    payload: PersonalExpenseUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    expense = _get_personal_or_404(db, expense_id, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        # el emoji admite null explícito (limpiarlo); el resto de campos no
        if value is None and field != "category_icon":
            continue
        setattr(expense, field, value)
    db.commit()
    db.refresh(expense)
    return expense


@router.delete("/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_personal_expense(
    expense_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    db.delete(_get_personal_or_404(db, expense_id, user))
    db.commit()


# ------------------------------------------------- nómina y presupuestos


def _finances_out(db: Session, user: User) -> dict:
    finance = db.get(UserFinance, user.id)
    budgets = db.scalars(
        select(UserBudget).where(UserBudget.user_id == user.id)
    ).all()
    return {
        "monthly_income": finance.monthly_income if finance else None,
        "budgets": [
            {"category": b.category, "limit_amount": b.limit_amount} for b in budgets
        ],
    }


@router.get("/finances", response_model=FinancesOut)
def get_finances(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return _finances_out(db, user)


@router.put("/finances", response_model=FinancesOut)
def put_finances(
    payload: FinancesUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    categorias = [b.category for b in payload.budgets]
    if len(categorias) != len(set(categorias)):
        raise HTTPException(
            status_code=400, detail="Solo puede haber un presupuesto por categoría"
        )

    finance = db.get(UserFinance, user.id)
    if finance is None:
        finance = UserFinance(user_id=user.id)
        db.add(finance)
    finance.monthly_income = payload.monthly_income

    # los presupuestos se reemplazan enteros: pocos y sin historia que conservar
    for budget in db.scalars(
        select(UserBudget).where(UserBudget.user_id == user.id)
    ).all():
        db.delete(budget)
    for item in payload.budgets:
        db.add(
            UserBudget(
                user_id=user.id,
                category=item.category,
                limit_amount=item.limit_amount,
            )
        )
    db.commit()
    return _finances_out(db, user)


# ----------------------------------------------------------- resumen mensual


@router.get("/summary", response_model=MonthlySummaryOut)
def monthly_summary(
    period: Optional[str] = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return personal_service.monthly_summary(
        db, user, period or personal_service.current_period()
    )
