"""Tests de gastos recurrentes (M7): la regla mensual materializa gastos
reales al consultar el grupo — sin cron, con el reparto vigente ese día."""

from datetime import datetime, timezone

from tests.conftest import as_decimal, make_standard_group, register_and_login


def current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def shift_period(period: str, months: int) -> str:
    year, month = map(int, period.split("-"))
    total = year * 12 + (month - 1) + months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def create_rule(client, headers, group_id, paid_by, **extra):
    payload = {
        "description": "Alquiler",
        "amount": "900",
        "category": "alojamiento",
        "paid_by": paid_by,
        "split_method": "percentage",
        "day_of_month": 1,
        **extra,
    }
    response = client.post(f"/groups/{group_id}/recurring", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_and_list_rules(client):
    headers = register_and_login(client, "ana@example.com")
    group, owner, _, _ = make_standard_group(client, headers)

    rule = create_rule(client, headers, group["id"], owner["id"],
                       start_period=shift_period(current_period(), 1))

    assert rule["description"] == "Alquiler"
    assert rule["day_of_month"] == 1
    assert rule["active"] is True

    listado = client.get(f"/groups/{group['id']}/recurring", headers=headers).json()
    assert [r["id"] for r in listado] == [rule["id"]]


def test_due_rule_materializes_expenses_on_listing(client):
    headers = register_and_login(client, "ana@example.com")
    group, owner, _, _ = make_standard_group(client, headers)
    # regla que arrancó el mes pasado: debe dos meses (pasado y actual)
    pasado = shift_period(current_period(), -1)
    rule = create_rule(client, headers, group["id"], owner["id"], start_period=pasado)

    gastos = client.get(f"/groups/{group['id']}/expenses", headers=headers).json()

    alquileres = [g for g in gastos if g["description"] == "Alquiler"]
    assert len(alquileres) == 2
    # reparto por Ingresos con los % del grupo (50/30/20)
    partes = sorted(as_decimal(s["computed_amount"]) for s in alquileres[0]["splits"])
    assert partes == [as_decimal("180"), as_decimal("270"), as_decimal("450")]

    # el puntero avanza: la regla queda esperando al mes que viene
    regla = client.get(f"/groups/{group['id']}/recurring", headers=headers).json()[0]
    assert regla["next_period"] == shift_period(current_period(), 1)

    # una segunda consulta no duplica nada
    gastos = client.get(f"/groups/{group['id']}/expenses", headers=headers).json()
    assert len([g for g in gastos if g["description"] == "Alquiler"]) == 2


def test_materialized_expenses_hit_balances(client):
    headers = register_and_login(client, "ana@example.com")
    group, owner, _, _ = make_standard_group(client, headers)
    create_rule(client, headers, group["id"], owner["id"],
                start_period=current_period(), day_of_month=1, amount="100")

    balances = client.get(f"/groups/{group['id']}/balances", headers=headers).json()

    del_owner = next(b for b in balances if b["member_id"] == owner["id"])
    # pagó 100 y su parte es 50 → +50
    assert as_decimal(del_owner["balance"]) == as_decimal("50")


def test_future_and_paused_rules_do_not_materialize(client):
    headers = register_and_login(client, "ana@example.com")
    group, owner, _, _ = make_standard_group(client, headers)
    futura = create_rule(client, headers, group["id"], owner["id"],
                         start_period=shift_period(current_period(), 1))
    vencida = create_rule(client, headers, group["id"], owner["id"],
                          description="Luz", start_period=current_period())
    client.patch(
        f"/groups/{group['id']}/recurring/{vencida['id']}",
        json={"active": False},
        headers=headers,
    )

    gastos = client.get(f"/groups/{group['id']}/expenses", headers=headers).json()

    assert gastos == []
    assert futura["next_period"] == shift_period(current_period(), 1)


def test_delete_rule_keeps_created_expenses(client):
    headers = register_and_login(client, "ana@example.com")
    group, owner, _, _ = make_standard_group(client, headers)
    rule = create_rule(client, headers, group["id"], owner["id"],
                       start_period=current_period())
    client.get(f"/groups/{group['id']}/expenses", headers=headers)

    response = client.delete(
        f"/groups/{group['id']}/recurring/{rule['id']}", headers=headers
    )
    assert response.status_code == 204

    gastos = client.get(f"/groups/{group['id']}/expenses", headers=headers).json()
    assert len(gastos) == 1  # el ya creado se queda
    assert client.get(f"/groups/{group['id']}/recurring", headers=headers).json() == []


def test_rule_validation(client):
    headers = register_and_login(client, "ana@example.com")
    group, owner, _, _ = make_standard_group(client, headers)

    for extra in [
        {"day_of_month": 0},
        {"day_of_month": 29},
        {"split_method": "exact"},
        {"amount": "0"},
    ]:
        payload = {
            "description": "X",
            "amount": "10",
            "paid_by": owner["id"],
            "split_method": "percentage",
            "day_of_month": 1,
            **extra,
        }
        response = client.post(
            f"/groups/{group['id']}/recurring", json=payload, headers=headers
        )
        assert response.status_code == 422, extra


def test_rules_require_membership(client):
    ana = register_and_login(client, "ana@example.com")
    bea = register_and_login(client, "bea2@example.com")
    group, owner, _, _ = make_standard_group(client, ana)

    response = client.get(f"/groups/{group['id']}/recurring", headers=bea)
    assert response.status_code == 403
