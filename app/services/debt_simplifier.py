"""Simplificación de deudas: minimizar el número de transacciones para saldar
un grupo, dado el balance neto de cada miembro.

Enfoque greedy sobre el "minimum cash flow problem": se empareja iterativamente
al mayor deudor con el mayor acreedor. No garantiza el mínimo absoluto de
transacciones (ese problema es NP-hard), pero produce como máximo n-1
transacciones y es O(n log n) usando heaps.
"""

import heapq
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

CENT = Decimal("0.01")


@dataclass
class Settlement:
    from_member_id: UUID
    to_member_id: UUID
    amount: Decimal


def simplify_debts(balances: dict[UUID, Decimal]) -> list[Settlement]:
    """Devuelve la lista de transacciones sugeridas para saldar el grupo.

    `balances`: balance neto por miembro (positivo = le deben, negativo = debe).
    Los balances con valor absoluto menor de 0.01 se consideran ya saldados.
    """
    # heaps de mínimos: los balances de deudores ya son negativos (el más
    # negativo sale primero); los de acreedores se niegan para el mismo efecto.
    debtors: list[tuple[Decimal, UUID]] = []
    creditors: list[tuple[Decimal, UUID]] = []

    for member_id, balance in balances.items():
        rounded = balance.quantize(CENT)
        if rounded <= -CENT:
            heapq.heappush(debtors, (rounded, member_id))
        elif rounded >= CENT:
            heapq.heappush(creditors, (-rounded, member_id))

    settlements: list[Settlement] = []
    while debtors and creditors:
        debt, debtor_id = heapq.heappop(debtors)
        neg_credit, creditor_id = heapq.heappop(creditors)
        credit = -neg_credit

        amount = min(-debt, credit)
        settlements.append(
            Settlement(from_member_id=debtor_id, to_member_id=creditor_id, amount=amount)
        )

        remaining_debt = debt + amount
        remaining_credit = credit - amount
        if remaining_debt <= -CENT:
            heapq.heappush(debtors, (remaining_debt, debtor_id))
        if remaining_credit >= CENT:
            heapq.heappush(creditors, (-remaining_credit, creditor_id))

    return settlements
