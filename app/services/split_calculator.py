"""Cálculo del importe que corresponde a cada participante de un gasto.

Regla de redondeo: cada parte se redondea a 2 decimales (ROUND_HALF_UP) y el
último participante de la lista absorbe la diferencia, de forma que la suma
de las partes siempre es exactamente igual al importe total del gasto.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from uuid import UUID

from app.models.expense import SplitMethod

TWO_PLACES = Decimal("0.01")
HUNDRED = Decimal("100")


class SplitValidationError(ValueError):
    """El reparto solicitado no es válido (porcentajes, importes, shares...)."""


@dataclass
class SplitSpec:
    """Especificación de la parte de un participante antes de calcular."""

    member_id: UUID
    percentage: Optional[Decimal] = None
    exact_amount: Optional[Decimal] = None
    shares: Optional[int] = None


def _q(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def compute_splits(
    amount: Decimal, split_method: SplitMethod, specs: list[SplitSpec]
) -> list[tuple[UUID, Decimal]]:
    """Devuelve [(member_id, importe_calculado), ...] según el método de división."""
    if not specs:
        raise SplitValidationError("El gasto debe tener al menos un participante")
    if amount <= 0:
        raise SplitValidationError("El importe del gasto debe ser mayor que 0")

    seen: set[UUID] = set()
    for spec in specs:
        if spec.member_id in seen:
            raise SplitValidationError("Hay participantes duplicados en el gasto")
        seen.add(spec.member_id)

    if split_method == SplitMethod.equal:
        return _split_equal(amount, specs)
    if split_method == SplitMethod.percentage:
        return _split_percentage(amount, specs)
    if split_method == SplitMethod.exact:
        return _split_exact(amount, specs)
    if split_method == SplitMethod.shares:
        return _split_shares(amount, specs)
    raise SplitValidationError(f"Método de división desconocido: {split_method}")


def _distribute(
    amount: Decimal, specs: list[SplitSpec], weights: list[Decimal]
) -> list[tuple[UUID, Decimal]]:
    """Reparto proporcional a `weights`; el último participante absorbe el redondeo."""
    total_weight = sum(weights)
    if total_weight <= 0:
        raise SplitValidationError("La suma de los pesos del reparto debe ser mayor que 0")

    result: list[tuple[UUID, Decimal]] = []
    allocated = Decimal("0")
    for spec, weight in zip(specs[:-1], weights[:-1]):
        part = _q(amount * weight / total_weight)
        result.append((spec.member_id, part))
        allocated += part
    result.append((specs[-1].member_id, _q(amount - allocated)))
    return result


def _split_equal(amount: Decimal, specs: list[SplitSpec]) -> list[tuple[UUID, Decimal]]:
    return _distribute(amount, specs, [Decimal("1")] * len(specs))


def _split_percentage(
    amount: Decimal, specs: list[SplitSpec]
) -> list[tuple[UUID, Decimal]]:
    percentages: list[Decimal] = []
    for spec in specs:
        if spec.percentage is None:
            raise SplitValidationError(
                "Todos los participantes deben indicar 'percentage' con este método"
            )
        if spec.percentage < 0 or spec.percentage > HUNDRED:
            raise SplitValidationError("Cada porcentaje debe estar entre 0 y 100")
        percentages.append(spec.percentage)

    total = sum(percentages)
    if total != HUNDRED:
        raise SplitValidationError(
            f"Los porcentajes del gasto deben sumar 100 (suma actual: {total})"
        )
    return _distribute(amount, specs, percentages)


def _split_exact(amount: Decimal, specs: list[SplitSpec]) -> list[tuple[UUID, Decimal]]:
    amounts: list[Decimal] = []
    for spec in specs:
        if spec.exact_amount is None:
            raise SplitValidationError(
                "Todos los participantes deben indicar 'exact_amount' con este método"
            )
        if spec.exact_amount < 0:
            raise SplitValidationError("Los importes exactos no pueden ser negativos")
        amounts.append(spec.exact_amount)

    total = sum(amounts)
    if total != amount:
        raise SplitValidationError(
            f"La suma de importes exactos ({total}) no coincide con el total del gasto ({amount})"
        )
    return [(spec.member_id, _q(a)) for spec, a in zip(specs, amounts)]


def _split_shares(amount: Decimal, specs: list[SplitSpec]) -> list[tuple[UUID, Decimal]]:
    weights: list[Decimal] = []
    for spec in specs:
        if spec.shares is None:
            raise SplitValidationError(
                "Todos los participantes deben indicar 'shares' con este método"
            )
        if spec.shares <= 0:
            raise SplitValidationError("Las shares deben ser enteros positivos")
        weights.append(Decimal(spec.shares))
    return _distribute(amount, specs, weights)
