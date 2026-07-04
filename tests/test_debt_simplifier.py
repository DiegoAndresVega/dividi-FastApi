from decimal import Decimal
from uuid import uuid4

from app.services.debt_simplifier import simplify_debts

A, B, C, D = uuid4(), uuid4(), uuid4(), uuid4()


def apply_settlements(balances, settlements):
    """Aplica las transacciones a los balances y devuelve el resultado."""
    result = dict(balances)
    for s in settlements:
        result[s.from_member_id] += s.amount
        result[s.to_member_id] -= s.amount
    return result


def test_grupo_saldado_no_genera_transacciones():
    assert simplify_debts({A: Decimal("0"), B: Decimal("0")}) == []


def test_un_solo_miembro():
    assert simplify_debts({A: Decimal("0")}) == []


def test_deuda_simple_entre_dos():
    settlements = simplify_debts({A: Decimal("-25"), B: Decimal("25")})
    assert len(settlements) == 1
    assert settlements[0].from_member_id == A
    assert settlements[0].to_member_id == B
    assert settlements[0].amount == Decimal("25")


def test_un_acreedor_varios_deudores():
    settlements = simplify_debts(
        {A: Decimal("60"), B: Decimal("-30"), C: Decimal("-30")}
    )
    assert len(settlements) == 2
    assert all(s.to_member_id == A for s in settlements)
    assert sum(s.amount for s in settlements) == Decimal("60")


def test_deuda_circular_se_simplifica():
    # A debe 10 a B, B debe 10 a C, C debe 10 a A → todos los balances netos
    # son 0 y no hace falta ninguna transacción
    assert simplify_debts({A: Decimal("0"), B: Decimal("0"), C: Decimal("0")}) == []


def test_emparejamiento_greedy_minimiza_transacciones():
    # el mayor deudor se empareja con el mayor acreedor: 2 transacciones,
    # no 3 (que saldría de emparejar cruzado)
    settlements = simplify_debts(
        {A: Decimal("-20"), B: Decimal("20"), C: Decimal("-5"), D: Decimal("5")}
    )
    assert len(settlements) == 2
    pairs = {(s.from_member_id, s.to_member_id, s.amount) for s in settlements}
    assert pairs == {(A, B, Decimal("20")), (C, D, Decimal("5"))}


def test_deudor_grande_paga_a_varios():
    settlements = simplify_debts(
        {A: Decimal("-100"), B: Decimal("70"), C: Decimal("30")}
    )
    assert len(settlements) == 2
    assert all(s.from_member_id == A for s in settlements)
    balances_finales = apply_settlements(
        {A: Decimal("-100"), B: Decimal("70"), C: Decimal("30")}, settlements
    )
    assert all(abs(b) < Decimal("0.01") for b in balances_finales.values())


def test_residuos_menores_de_un_centimo_se_ignoran():
    settlements = simplify_debts({A: Decimal("0.004"), B: Decimal("-0.004")})
    assert settlements == []


def test_las_transacciones_saldan_todos_los_balances():
    balances = {
        A: Decimal("123.45"),
        B: Decimal("-67.89"),
        C: Decimal("-55.56"),
        D: Decimal("0"),
    }
    settlements = simplify_debts(balances)
    finales = apply_settlements(balances, settlements)
    assert all(abs(b) < Decimal("0.01") for b in finales.values())
    # nunca más de n-1 transacciones
    assert len(settlements) <= len(balances) - 1
