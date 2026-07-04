"""Cálculo del balance neto de cada miembro de un grupo.

balance = (gastos adelantados) - (parte que le corresponde de cada gasto)
        + (pagos realizados)   - (pagos recibidos)

Un pago realizado es dinero aportado (reduce tu deuda), igual que adelantar un
gasto; un pago recibido es dinero cobrado (reduce lo que te deben).
Balance positivo = le deben dinero. Negativo = debe dinero.
"""

from decimal import Decimal
from uuid import UUID

from app.models.group import Group

CENT = Decimal("0.01")


def compute_group_balances(group: Group) -> dict[UUID, Decimal]:
    balances: dict[UUID, Decimal] = {m.id: Decimal("0") for m in group.members}

    for expense in group.expenses:
        balances[expense.paid_by_id] += expense.amount
        for split in expense.splits:
            balances[split.group_member_id] -= split.computed_amount

    for payment in group.payments:
        balances[payment.from_member_id] += payment.amount
        balances[payment.to_member_id] -= payment.amount

    return {member_id: b.quantize(CENT) for member_id, b in balances.items()}
