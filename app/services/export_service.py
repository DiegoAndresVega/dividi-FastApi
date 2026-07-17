"""Exportación CSV del grupo (M9): gastos con la parte de cada miembro,
pagos, balances y el settle-up sugerido. Con `;` y coma decimal, que es
lo que espera el Excel en español; BOM para que detecte UTF-8."""

import csv
import io
from datetime import datetime, timezone
from decimal import Decimal

from app.models import Group


def _dec(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}".replace(".", ",")


def build_csv(group: Group, balances: dict, settlements: list) -> str:
    members = list(group.members)
    names = {m.id: m.display_name for m in members}

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")

    writer.writerow(["Grupo", group.name, group.default_currency])
    writer.writerow(
        ["Exportado", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")]
    )
    writer.writerow([])

    writer.writerow(["GASTOS"])
    writer.writerow(
        ["Fecha", "Descripción", "Categoría", "Pagó", "Importe"]
        + [m.display_name for m in members]
    )
    total = Decimal("0")
    for expense in sorted(group.expenses, key=lambda e: e.created_at):
        parts = {s.group_member_id: s.computed_amount for s in expense.splits}
        writer.writerow(
            [
                expense.created_at.date().isoformat(),
                expense.description,
                expense.category,
                names.get(expense.paid_by_id, "—"),
                _dec(expense.amount),
            ]
            + [_dec(parts.get(m.id)) for m in members]
        )
        total += expense.amount
    writer.writerow(["", "", "", "TOTAL", _dec(total)])
    writer.writerow([])

    if group.payments:
        writer.writerow(["PAGOS"])
        writer.writerow(["Fecha", "De", "A", "Importe"])
        for payment in sorted(group.payments, key=lambda p: p.paid_at):
            writer.writerow(
                [
                    payment.paid_at.date().isoformat(),
                    names.get(payment.from_member_id, "—"),
                    names.get(payment.to_member_id, "—"),
                    _dec(payment.amount),
                ]
            )
        writer.writerow([])

    writer.writerow(["BALANCES"])
    writer.writerow(["Miembro", "Balance"])
    for member in members:
        writer.writerow([member.display_name, _dec(balances[member.id])])
    writer.writerow([])

    writer.writerow(["SALDAR CUENTAS (sugerencia)"])
    writer.writerow(["De", "A", "Importe"])
    for settlement in settlements:
        writer.writerow(
            [
                names.get(settlement.from_member_id, "—"),
                names.get(settlement.to_member_id, "—"),
                _dec(settlement.amount),
            ]
        )

    # BOM: el Excel español abre UTF-8 sin preguntar
    return "﻿" + buffer.getvalue()
