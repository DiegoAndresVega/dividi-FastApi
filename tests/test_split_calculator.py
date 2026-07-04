from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.expense import SplitMethod
from app.services.split_calculator import (
    SplitSpec,
    SplitValidationError,
    compute_splits,
)

A, B, C = uuid4(), uuid4(), uuid4()


def total(result) -> Decimal:
    return sum(amount for _, amount in result)


class TestEqual:
    def test_division_exacta(self):
        result = compute_splits(
            Decimal("30"), SplitMethod.equal, [SplitSpec(A), SplitSpec(B), SplitSpec(C)]
        )
        assert result == [(A, Decimal("10")), (B, Decimal("10")), (C, Decimal("10"))]

    def test_redondeo_lo_absorbe_el_ultimo(self):
        result = compute_splits(
            Decimal("10"), SplitMethod.equal, [SplitSpec(A), SplitSpec(B), SplitSpec(C)]
        )
        assert result == [(A, Decimal("3.33")), (B, Decimal("3.33")), (C, Decimal("3.34"))]
        assert total(result) == Decimal("10")

    def test_importe_minimo(self):
        result = compute_splits(
            Decimal("0.01"), SplitMethod.equal, [SplitSpec(A), SplitSpec(B), SplitSpec(C)]
        )
        assert total(result) == Decimal("0.01")

    def test_un_solo_participante(self):
        result = compute_splits(Decimal("25.50"), SplitMethod.equal, [SplitSpec(A)])
        assert result == [(A, Decimal("25.50"))]


class TestPercentage:
    def test_reparto_por_porcentajes(self):
        result = compute_splits(
            Decimal("100"),
            SplitMethod.percentage,
            [
                SplitSpec(A, percentage=Decimal("50")),
                SplitSpec(B, percentage=Decimal("30")),
                SplitSpec(C, percentage=Decimal("20")),
            ],
        )
        assert result == [(A, Decimal("50")), (B, Decimal("30")), (C, Decimal("20"))]

    def test_porcentajes_con_redondeo(self):
        result = compute_splits(
            Decimal("100"),
            SplitMethod.percentage,
            [
                SplitSpec(A, percentage=Decimal("33.33")),
                SplitSpec(B, percentage=Decimal("33.33")),
                SplitSpec(C, percentage=Decimal("33.34")),
            ],
        )
        assert total(result) == Decimal("100")
        assert result[0][1] == Decimal("33.33")

    def test_suma_distinta_de_100_falla(self):
        with pytest.raises(SplitValidationError, match="sumar 100"):
            compute_splits(
                Decimal("100"),
                SplitMethod.percentage,
                [
                    SplitSpec(A, percentage=Decimal("60")),
                    SplitSpec(B, percentage=Decimal("50")),
                ],
            )

    def test_porcentaje_faltante_falla(self):
        with pytest.raises(SplitValidationError, match="percentage"):
            compute_splits(
                Decimal("100"),
                SplitMethod.percentage,
                [SplitSpec(A, percentage=Decimal("100")), SplitSpec(B)],
            )

    def test_porcentaje_cero_permitido(self):
        result = compute_splits(
            Decimal("50"),
            SplitMethod.percentage,
            [
                SplitSpec(A, percentage=Decimal("100")),
                SplitSpec(B, percentage=Decimal("0")),
            ],
        )
        assert result == [(A, Decimal("50")), (B, Decimal("0"))]


class TestExact:
    def test_importes_exactos(self):
        result = compute_splits(
            Decimal("50"),
            SplitMethod.exact,
            [
                SplitSpec(A, exact_amount=Decimal("12.75")),
                SplitSpec(B, exact_amount=Decimal("37.25")),
            ],
        )
        assert result == [(A, Decimal("12.75")), (B, Decimal("37.25"))]

    def test_suma_no_cuadra_falla(self):
        with pytest.raises(SplitValidationError, match="no coincide"):
            compute_splits(
                Decimal("50"),
                SplitMethod.exact,
                [
                    SplitSpec(A, exact_amount=Decimal("10")),
                    SplitSpec(B, exact_amount=Decimal("10")),
                ],
            )

    def test_importe_faltante_falla(self):
        with pytest.raises(SplitValidationError, match="exact_amount"):
            compute_splits(
                Decimal("50"),
                SplitMethod.exact,
                [SplitSpec(A, exact_amount=Decimal("50")), SplitSpec(B)],
            )


class TestShares:
    def test_reparto_por_shares(self):
        result = compute_splits(
            Decimal("60"),
            SplitMethod.shares,
            [SplitSpec(A, shares=2), SplitSpec(B, shares=1)],
        )
        assert result == [(A, Decimal("40")), (B, Decimal("20"))]

    def test_shares_con_redondeo(self):
        result = compute_splits(
            Decimal("100"),
            SplitMethod.shares,
            [SplitSpec(A, shares=1), SplitSpec(B, shares=1), SplitSpec(C, shares=1)],
        )
        assert result == [(A, Decimal("33.33")), (B, Decimal("33.33")), (C, Decimal("33.34"))]
        assert total(result) == Decimal("100")

    def test_shares_cero_falla(self):
        with pytest.raises(SplitValidationError, match="shares"):
            compute_splits(
                Decimal("60"),
                SplitMethod.shares,
                [SplitSpec(A, shares=0), SplitSpec(B, shares=1)],
            )

    def test_shares_faltante_falla(self):
        with pytest.raises(SplitValidationError, match="shares"):
            compute_splits(
                Decimal("60"),
                SplitMethod.shares,
                [SplitSpec(A, shares=1), SplitSpec(B)],
            )


class TestValidacionesGenerales:
    def test_sin_participantes_falla(self):
        with pytest.raises(SplitValidationError, match="al menos un participante"):
            compute_splits(Decimal("10"), SplitMethod.equal, [])

    def test_importe_cero_falla(self):
        with pytest.raises(SplitValidationError, match="mayor que 0"):
            compute_splits(Decimal("0"), SplitMethod.equal, [SplitSpec(A)])

    def test_importe_negativo_falla(self):
        with pytest.raises(SplitValidationError, match="mayor que 0"):
            compute_splits(Decimal("-5"), SplitMethod.equal, [SplitSpec(A)])

    def test_participante_duplicado_falla(self):
        with pytest.raises(SplitValidationError, match="duplicados"):
            compute_splits(
                Decimal("10"), SplitMethod.equal, [SplitSpec(A), SplitSpec(A)]
            )
