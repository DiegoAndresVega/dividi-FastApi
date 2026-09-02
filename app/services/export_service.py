"""Exportación CSV del grupo (M9): gastos con la parte de cada miembro,
pagos, balances y el settle-up sugerido. Con `;` y coma decimal, que es
lo que espera el Excel en español; BOM para que detecte UTF-8."""

import csv
import io
import re
from datetime import datetime, timezone
from decimal import Decimal

from app.models import Group

# Con estos caracteres una hoja de cálculo deja de leer la celda como texto y
# la interpreta: fórmula (=), signo (+ -), referencia a otra hoja (@) y los que
# Excel usa para separar al pegar (tabulador y retornos).
INICIOS_DE_FORMULA = ("=", "+", "-", "@", "\t", "\r", "\n")

# Lo que produce _dec: «1234,50» o «-12,50». Un importe negativo empieza por
# «-», pero Excel lo lee como número: ponerle el apóstrofo delante convertiría
# en texto todos los balances en contra y el CSV dejaría de sumar.
_NUMERO = re.compile(r"^-?\d+(?:,\d+)?$")


def _dec(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}".replace(".", ",")


def _neutralizar(valor: str) -> str:
    """Antepone un apóstrofo al texto que una hoja de cálculo ejecutaría.

    El apóstrofo no se ve al abrir el fichero: le dice a Excel y a LibreOffice
    que la celda es texto literal.
    """
    if not isinstance(valor, str) or not valor.startswith(INICIOS_DE_FORMULA):
        return valor
    if _NUMERO.match(valor):
        return valor
    return f"'{valor}"


class _EscritorNeutralizado:
    """Escritor CSV que pasa cada celda por `_neutralizar`.

    Envolver el escritor en vez de escapar en cada `writerow` deja el arreglo
    en un único sitio: vale para gastos, pagos, balances y settle-up, y para
    las secciones que se añadan después sin tener que acordarse.
    """

    def __init__(self, destino: io.StringIO) -> None:
        self._writer = csv.writer(destino, delimiter=";")

    def writerow(self, fila: list) -> None:
        self._writer.writerow([_neutralizar(celda) for celda in fila])


def build_csv(group: Group, balances: dict, settlements: list) -> str:
    members = list(group.members)
    names = {m.id: m.display_name for m in members}

    buffer = io.StringIO()
    writer = _EscritorNeutralizado(buffer)

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
