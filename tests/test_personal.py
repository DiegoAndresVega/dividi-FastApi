"""Tests de «Mi dinero» (M11 + M12): gastos personales, nómina, presupuestos
y el resumen mensual que junta lo personal con tu parte de los grupos."""

from datetime import datetime, timezone

from tests.conftest import as_decimal, make_standard_group, register_and_login


def current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def create_personal(client, headers, description="Gimnasio", amount="39.90",
                    category="ocio", category_icon=None, created_at=None):
    payload = {"description": description, "amount": amount, "category": category}
    if category_icon is not None:
        payload["category_icon"] = category_icon
    if created_at is not None:
        payload["created_at"] = created_at
    response = client.post("/me/expenses", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


# ------------------------------------------------------- gastos personales


def test_create_and_list_personal_expenses(client):
    headers = register_and_login(client, "ana@example.com")

    gasto = create_personal(client, headers)
    assert gasto["description"] == "Gimnasio"
    assert as_decimal(gasto["amount"]) == as_decimal("39.90")
    assert gasto["category"] == "ocio"

    listado = client.get("/me/expenses", headers=headers).json()
    assert [g["id"] for g in listado] == [gasto["id"]]


def test_personal_expenses_are_private(client):
    ana = register_and_login(client, "ana@example.com")
    bea = register_and_login(client, "bea@example.com")
    gasto = create_personal(client, ana)

    assert client.get("/me/expenses", headers=bea).json() == []
    assert (
        client.patch(
            f"/me/expenses/{gasto['id']}",
            json={"amount": "1"},
            headers=bea,
        ).status_code
        == 404
    )


def test_personal_expense_filters(client):
    headers = register_and_login(client, "ana@example.com")
    create_personal(client, headers, description="Café", category="comida")
    create_personal(client, headers, description="Cine", category="ocio")
    create_personal(
        client,
        headers,
        description="Viejo",
        category="comida",
        created_at="2020-01-15T12:00:00Z",
    )

    por_categoria = client.get("/me/expenses?category=comida", headers=headers).json()
    assert {g["description"] for g in por_categoria} == {"Café", "Viejo"}

    recientes = client.get(
        "/me/expenses?date_from=2026-01-01T00:00:00Z", headers=headers
    ).json()
    assert {g["description"] for g in recientes} == {"Café", "Cine"}


def test_update_and_delete_personal_expense(client):
    headers = register_and_login(client, "ana@example.com")
    gasto = create_personal(client, headers)

    actualizado = client.patch(
        f"/me/expenses/{gasto['id']}",
        json={"description": "Gimnasio mensual", "amount": "45"},
        headers=headers,
    )
    assert actualizado.status_code == 200, actualizado.text
    assert actualizado.json()["description"] == "Gimnasio mensual"
    assert as_decimal(actualizado.json()["amount"]) == as_decimal("45")

    assert (
        client.delete(f"/me/expenses/{gasto['id']}", headers=headers).status_code
        == 204
    )
    assert client.get("/me/expenses", headers=headers).json() == []


def test_personal_expense_validation(client):
    headers = register_and_login(client, "ana@example.com")

    for payload in [
        {"description": "", "amount": "10"},
        {"description": "X", "amount": "0"},
        {"description": "X", "amount": "10", "category": "   "},
        {"description": "X", "amount": "10", "category": "x" * 31},
    ]:
        response = client.post("/me/expenses", json=payload, headers=headers)
        assert response.status_code == 422, payload


def test_personal_expense_categoria_personalizada(client):
    headers = register_and_login(client, "ana@example.com")

    gasto = create_personal(
        client, headers,
        description="Recibo del agua",
        category="Agua",
        category_icon="💧",
    )
    assert gasto["category"] == "agua"
    assert gasto["category_icon"] == "💧"

    # el resumen mensual también agrupa por la categoría inventada
    resumen = client.get("/me/summary", headers=headers).json()
    agua = next(c for c in resumen["by_category"] if c["category"] == "agua")
    assert as_decimal(agua["personal"]) == as_decimal("39.90")


def test_personal_requires_auth(client):
    assert client.get("/me/expenses").status_code == 401
    assert client.get("/me/finances").status_code == 401
    assert client.get("/me/summary").status_code == 401


# ------------------------------------------------- nómina y presupuestos


def test_finances_default_empty(client):
    headers = register_and_login(client, "ana@example.com")

    finanzas = client.get("/me/finances", headers=headers).json()

    assert finanzas["monthly_income"] is None
    assert finanzas["budgets"] == []


def test_put_finances_sets_income_and_budgets(client):
    headers = register_and_login(client, "ana@example.com")

    response = client.put(
        "/me/finances",
        json={
            "monthly_income": "1850",
            "budgets": [
                {"category": "comida", "limit_amount": "220"},
                {"category": "ocio", "limit_amount": "80"},
            ],
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    finanzas = response.json()
    assert as_decimal(finanzas["monthly_income"]) == as_decimal("1850")
    assert len(finanzas["budgets"]) == 2


def test_put_finances_replaces_budgets(client):
    headers = register_and_login(client, "ana@example.com")
    client.put(
        "/me/finances",
        json={
            "monthly_income": "1850",
            "budgets": [{"category": "comida", "limit_amount": "220"}],
        },
        headers=headers,
    )

    respuesta = client.put(
        "/me/finances",
        json={
            "monthly_income": None,
            "budgets": [{"category": "transporte", "limit_amount": "60"}],
        },
        headers=headers,
    )

    finanzas = respuesta.json()
    assert finanzas["monthly_income"] is None
    assert [b["category"] for b in finanzas["budgets"]] == ["transporte"]


def test_put_finances_rejects_duplicate_categories(client):
    headers = register_and_login(client, "ana@example.com")

    response = client.put(
        "/me/finances",
        json={
            "budgets": [
                {"category": "comida", "limit_amount": "100"},
                {"category": "comida", "limit_amount": "200"},
            ],
        },
        headers=headers,
    )

    assert response.status_code == 400


# ----------------------------------------------------------- resumen mensual


def test_summary_combines_personal_and_group_share(client):
    headers = register_and_login(client, "ana@example.com")
    group, owner_member, _, _ = make_standard_group(client, headers)

    # gasto de grupo de 100 por Ingresos: al owner (50 %) le tocan 50
    response = client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Compra",
            "amount": "100",
            "paid_by": owner_member["id"],
            "split_method": "percentage",
            "category": "comida",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text

    create_personal(client, headers, description="Café", amount="2.40",
                    category="comida")
    client.put(
        "/me/finances",
        json={
            "monthly_income": "1850",
            "budgets": [{"category": "comida", "limit_amount": "220"}],
        },
        headers=headers,
    )

    resumen = client.get("/me/summary", headers=headers).json()

    assert resumen["period"] == current_period()
    assert as_decimal(resumen["personal_total"]) == as_decimal("2.40")
    assert as_decimal(resumen["groups_share_total"]) == as_decimal("50")
    assert as_decimal(resumen["total_spent"]) == as_decimal("52.40")
    assert as_decimal(resumen["available"]) == as_decimal("1797.60")

    comida = next(c for c in resumen["by_category"] if c["category"] == "comida")
    assert as_decimal(comida["personal"]) == as_decimal("2.40")
    assert as_decimal(comida["groups_share"]) == as_decimal("50")
    assert as_decimal(comida["total"]) == as_decimal("52.40")
    assert as_decimal(comida["budget_limit"]) == as_decimal("220")


def test_summary_without_income_has_no_available(client):
    headers = register_and_login(client, "ana@example.com")
    create_personal(client, headers, amount="10")

    resumen = client.get("/me/summary", headers=headers).json()

    assert resumen["monthly_income"] is None
    assert resumen["available"] is None
    assert as_decimal(resumen["total_spent"]) == as_decimal("10")


def test_summary_respects_period(client):
    headers = register_and_login(client, "ana@example.com")
    create_personal(client, headers, created_at="2020-01-15T12:00:00Z", amount="99")
    create_personal(client, headers, amount="10")

    actual = client.get("/me/summary", headers=headers).json()
    antiguo = client.get("/me/summary?period=2020-01", headers=headers).json()

    assert as_decimal(actual["total_spent"]) == as_decimal("10")
    assert as_decimal(antiguo["total_spent"]) == as_decimal("99")
