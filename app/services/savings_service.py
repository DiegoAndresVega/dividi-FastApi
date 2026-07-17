"""Lógica de dominio de los planes de ahorro.

La proyección no mira gastos reales (la app no los conoce del todo):
solo hace las cuentas entre lo que queda y el ritmo mensual declarado.
"""

import math
from datetime import datetime, timezone
from decimal import Decimal

from app.models.savings import SavingsEntryKind, SavingsPlan


class SavingsValidationError(Exception):
    """Regla de dominio incumplida; el router la traduce a HTTP 400."""


def current_period(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y-%m")


def shift_period(period: str, months: int) -> str:
    year, month = map(int, period.split("-"))
    total = year * 12 + (month - 1) + months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def remaining_amount(plan: SavingsPlan) -> Decimal:
    return max(plan.target_amount - plan.saved_amount, Decimal("0"))


def months_to_goal(plan: SavingsPlan) -> int:
    remaining = remaining_amount(plan)
    if remaining <= 0:
        return 0
    return math.ceil(remaining / plan.monthly_amount)


def projected_period(plan: SavingsPlan, now: datetime | None = None) -> str:
    return shift_period(current_period(now), months_to_goal(plan))


def is_period_confirmed(plan: SavingsPlan, period: str) -> bool:
    return any(
        entry.kind == SavingsEntryKind.monthly and entry.period == period
        for entry in plan.entries
    )


def validate_entry(
    plan: SavingsPlan, kind: SavingsEntryKind, amount: Decimal, period: str | None
) -> None:
    if kind == SavingsEntryKind.monthly:
        if amount < 0:
            raise SavingsValidationError(
                "La confirmación de un mes no puede ser negativa; "
                "para sacar dinero de la hucha usa un ajuste"
            )
        if is_period_confirmed(plan, period):
            raise SavingsValidationError(f"El mes {period} ya está confirmado")
    else:
        if amount == 0:
            raise SavingsValidationError("Un ajuste de 0 no cambia nada")
        if plan.saved_amount + amount < 0:
            raise SavingsValidationError("La hucha no puede quedar en negativo")
