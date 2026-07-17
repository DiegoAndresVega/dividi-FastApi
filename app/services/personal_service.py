"""Resumen mensual de «Mi dinero»: junta los gastos personales del usuario
con su parte (computed_amount) de los gastos de todos sus grupos."""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Expense,
    ExpenseSplit,
    GroupMember,
    PersonalExpense,
    User,
    UserBudget,
    UserFinance,
)


def current_period(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y-%m")


def period_window(period: str) -> tuple[datetime, datetime]:
    """[inicio, fin) del mes «YYYY-MM» en UTC."""
    year, month = map(int, period.split("-"))
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = (
        datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        if month == 12
        else datetime(year, month + 1, 1, tzinfo=timezone.utc)
    )
    return start, end


def monthly_summary(db: Session, user: User, period: str) -> dict:
    start, end = period_window(period)
    zero = Decimal("0")

    personal_by_cat: dict[str, Decimal] = {}
    for expense in db.scalars(
        select(PersonalExpense).where(
            PersonalExpense.user_id == user.id,
            PersonalExpense.created_at >= start,
            PersonalExpense.created_at < end,
        )
    ):
        personal_by_cat[expense.category] = (
            personal_by_cat.get(expense.category, zero) + expense.amount
        )

    share_by_cat: dict[str, Decimal] = {}
    filas = db.execute(
        select(Expense.category, ExpenseSplit.computed_amount)
        .join(ExpenseSplit, ExpenseSplit.expense_id == Expense.id)
        .join(GroupMember, GroupMember.id == ExpenseSplit.group_member_id)
        .where(
            GroupMember.user_id == user.id,
            Expense.created_at >= start,
            Expense.created_at < end,
        )
    ).all()
    for categoria, importe in filas:
        share_by_cat[categoria] = share_by_cat.get(categoria, zero) + importe

    budgets = {
        b.category: b.limit_amount
        for b in db.scalars(select(UserBudget).where(UserBudget.user_id == user.id))
    }
    finance = db.get(UserFinance, user.id)
    income = finance.monthly_income if finance else None

    categorias = set(personal_by_cat) | set(share_by_cat) | set(budgets)
    by_category = sorted(
        (
            {
                "category": categoria,
                "personal": personal_by_cat.get(categoria, zero),
                "groups_share": share_by_cat.get(categoria, zero),
                "total": personal_by_cat.get(categoria, zero)
                + share_by_cat.get(categoria, zero),
                "budget_limit": budgets.get(categoria),
            }
            for categoria in categorias
        ),
        key=lambda fila: fila["total"],
        reverse=True,
    )

    personal_total = sum(personal_by_cat.values(), zero)
    share_total = sum(share_by_cat.values(), zero)
    total = personal_total + share_total
    return {
        "period": period,
        "monthly_income": income,
        "personal_total": personal_total,
        "groups_share_total": share_total,
        "total_spent": total,
        "available": None if income is None else income - total,
        "by_category": by_category,
    }
