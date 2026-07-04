from decimal import Decimal

from tests.conftest import as_decimal, make_standard_group, register_and_login


def get_balances(client, headers, group_id) -> dict:
    response = client.get(f"/groups/{group_id}/balances", headers=headers)
    assert response.status_code == 200, response.text
    return {b["member_id"]: as_decimal(b["balance"]) for b in response.json()}


def test_grupo_sin_gastos_todo_a_cero(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)
    balances = get_balances(client, headers, group["id"])
    assert all(b == 0 for b in balances.values())


def test_balance_tras_gasto_equal(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)
    client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Cena",
            "amount": "90",
            "paid_by": owner["id"],
            "split_method": "equal",
        },
        headers=headers,
    )
    balances = get_balances(client, headers, group["id"])
    assert balances[owner["id"]] == Decimal("60")
    assert balances[bea["id"]] == Decimal("-30")
    assert balances[carlos["id"]] == Decimal("-30")


def test_un_pago_reduce_la_deuda(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)
    client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Cena",
            "amount": "90",
            "paid_by": owner["id"],
            "split_method": "equal",
        },
        headers=headers,
    )
    response = client.post(
        f"/groups/{group['id']}/payments",
        json={"from_member_id": bea["id"], "to_member_id": owner["id"], "amount": "30"},
        headers=headers,
    )
    assert response.status_code == 201, response.text

    balances = get_balances(client, headers, group["id"])
    assert balances[owner["id"]] == Decimal("30")
    assert balances[bea["id"]] == Decimal("0")
    assert balances[carlos["id"]] == Decimal("-30")


def test_la_suma_de_balances_es_cero(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)
    client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Hotel",
            "amount": "123.45",
            "paid_by": bea["id"],
            "split_method": "percentage",
        },
        headers=headers,
    )
    client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Taxi",
            "amount": "17.77",
            "paid_by": carlos["id"],
            "split_method": "equal",
        },
        headers=headers,
    )
    balances = get_balances(client, headers, group["id"])
    assert sum(balances.values()) == Decimal("0")


def test_settle_up_devuelve_transacciones_que_saldan_el_grupo(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)
    client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Cena",
            "amount": "90",
            "paid_by": owner["id"],
            "split_method": "equal",
        },
        headers=headers,
    )
    response = client.get(f"/groups/{group['id']}/settle-up", headers=headers)
    assert response.status_code == 200, response.text
    settlements = response.json()
    assert len(settlements) == 2
    assert all(s["to_member_id"] == owner["id"] for s in settlements)
    assert sum(as_decimal(s["amount"]) for s in settlements) == Decimal("60")

    # registrar los pagos sugeridos deja el grupo saldado
    for s in settlements:
        client.post(
            f"/groups/{group['id']}/payments",
            json={
                "from_member_id": s["from_member_id"],
                "to_member_id": s["to_member_id"],
                "amount": s["amount"],
            },
            headers=headers,
        )
    balances = get_balances(client, headers, group["id"])
    assert all(b == 0 for b in balances.values())
    assert client.get(f"/groups/{group['id']}/settle-up", headers=headers).json() == []
