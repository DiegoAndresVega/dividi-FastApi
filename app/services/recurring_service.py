"""Materialización de gastos recurrentes (M7).

Sin cron: cuando alguien consulta los gastos o balances de un grupo, las
reglas activas crean los gastos ya vencidos. El reparto se calcula con el
estado del grupo EN ESE MOMENTO («los % vigentes ese día» de la propuesta
se interpreta como: al materializar, no al crear la regla).
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Expense, ExpenseSplit, Group, RecurringExpense, SplitMethod
from app.services.split_calculator import (
    SplitSpec,
    SplitValidationError,
    compute_splits,
)


def shift_period(period: str, months: int) -> str:
    year, month = map(int, period.split("-"))
    total = year * 12 + (month - 1) + months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def due_date(period: str, day_of_month: int) -> datetime:
    year, month = map(int, period.split("-"))
    # a las 09:00 UTC: hora de mañana razonable en cualquier huso europeo
    return datetime(year, month, day_of_month, 9, 0, tzinfo=timezone.utc)


def default_start_period(day_of_month: int, now: datetime | None = None) -> str:
    """Primer mes a materializar: este mes si el día aún no pasó, si no el que viene."""
    now = now or datetime.now(timezone.utc)
    period = now.strftime("%Y-%m")
    return period if day_of_month >= now.day else shift_period(period, 1)


def _specs_for(rule: RecurringExpense, group: Group) -> list[SplitSpec]:
    if rule.split_method == SplitMethod.equal:
        return [SplitSpec(member_id=m.id) for m in group.members]
    return [
        SplitSpec(member_id=m.id, percentage=m.default_percentage)
        for m in group.members
    ]


def materialize_due(db: Session, group: Group, now: datetime | None = None) -> int:
    """Crea los gastos vencidos de las reglas activas del grupo.

    Devuelve cuántos gastos se crearon (0 si no tocaba ninguno).
    """
    now = now or datetime.now(timezone.utc)
    rules = db.scalars(
        select(RecurringExpense).where(
            RecurringExpense.group_id == group.id,
            RecurringExpense.active.is_(True),
        )
    ).all()

    created = 0
    for rule in rules:
        while due_date(rule.next_period, rule.day_of_month) <= now:
            if not any(m.id == rule.paid_by_id for m in group.members):
                # el pagador ya no está en el grupo: la regla se pausa en vez
                # de romper la consulta; un admin puede reactivarla editándola
                rule.active = False
                break
            specs = _specs_for(rule, group)
            try:
                computed = compute_splits(rule.amount, rule.split_method, specs)
            except SplitValidationError:
                rule.active = False
                break
            expense = Expense(
                group_id=group.id,
                description=rule.description,
                amount=rule.amount,
                currency=group.default_currency,
                category=rule.category,
                paid_by_id=rule.paid_by_id,
                split_method=rule.split_method,
                created_by_id=rule.created_by_id,
                created_at=due_date(rule.next_period, rule.day_of_month),
            )
            spec_by_member = {s.member_id: s for s in specs}
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
            db.add(expense)
            rule.next_period = shift_period(rule.next_period, 1)
            created += 1

    if created:
        db.commit()
    return created
