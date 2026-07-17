"""Tests de planes de ahorro personales (pestaña «Mi dinero»).

La mecánica es de confirmación manual: la app no conoce las cuentas reales
del usuario, así que cada mes es él quien pulsa «Logrado» (confirmando la
cantidad, que puede diferir de la planeada) o registra lo que consiguió.
La hucha además se ajusta a mano en cualquier momento, sin justificar.
"""

from datetime import datetime, timezone

from tests.conftest import as_decimal, register_and_login


def current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def shift_period(period: str, months: int) -> str:
    year, month = map(int, period.split("-"))
    total = year * 12 + (month - 1) + months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def create_plan(
    client, headers, name="Viaje a Japón", target="2400", monthly="300", saved=None
):
    payload = {"name": name, "target_amount": target, "monthly_amount": monthly}
    if saved is not None:
        payload["saved_amount"] = saved
    response = client.post("/savings-plans", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------- creación


def test_create_plan_returns_projection(client):
    headers = register_and_login(client, "ana@example.com")

    plan = create_plan(client, headers)

    assert plan["name"] == "Viaje a Japón"
    assert as_decimal(plan["target_amount"]) == as_decimal("2400")
    assert as_decimal(plan["monthly_amount"]) == as_decimal("300")
    assert as_decimal(plan["saved_amount"]) == as_decimal("0")
    assert as_decimal(plan["remaining_amount"]) == as_decimal("2400")
    assert plan["months_to_goal"] == 8
    assert plan["projected_period"] == shift_period(current_period(), 8)
    assert plan["current_period"] == current_period()
    assert plan["is_current_period_confirmed"] is False
    assert plan["is_completed"] is False


def test_create_plan_with_initial_savings(client):
    headers = register_and_login(client, "ana@example.com")

    plan = create_plan(client, headers, saved="600")

    assert as_decimal(plan["saved_amount"]) == as_decimal("600")
    assert as_decimal(plan["remaining_amount"]) == as_decimal("1800")
    assert plan["months_to_goal"] == 6


def test_create_plan_rejects_non_positive_amounts(client):
    headers = register_and_login(client, "ana@example.com")

    for payload in [
        {"name": "X", "target_amount": "0", "monthly_amount": "100"},
        {"name": "X", "target_amount": "1000", "monthly_amount": "0"},
        {"name": "X", "target_amount": "1000", "monthly_amount": "-50"},
    ]:
        response = client.post("/savings-plans", json=payload, headers=headers)
        assert response.status_code == 422, response.text


def test_multiple_plans_allowed(client):
    headers = register_and_login(client, "ana@example.com")

    create_plan(client, headers, name="Viaje a Japón")
    create_plan(client, headers, name="Colchón", target="1200", monthly="100")

    response = client.get("/savings-plans", headers=headers)
    assert response.status_code == 200
    names = [plan["name"] for plan in response.json()]
    assert names == ["Viaje a Japón", "Colchón"]


# ---------------------------------------------------------------- acceso


def test_plans_are_private_per_user(client):
    ana = register_and_login(client, "ana@example.com")
    bea = register_and_login(client, "bea@example.com")
    plan = create_plan(client, ana)

    assert client.get("/savings-plans", headers=bea).json() == []
    response = client.get(f"/savings-plans/{plan['id']}", headers=bea)
    assert response.status_code == 404


def test_requires_authentication(client):
    assert client.get("/savings-plans").status_code == 401


# ---------------------------------------------------------------- edición


def test_patch_plan_recalculates_projection(client):
    headers = register_and_login(client, "ana@example.com")
    plan = create_plan(client, headers)

    response = client.patch(
        f"/savings-plans/{plan['id']}",
        json={"name": "Japón 2027", "monthly_amount": "600"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["name"] == "Japón 2027"
    assert updated["months_to_goal"] == 4


def test_delete_plan(client):
    headers = register_and_login(client, "ana@example.com")
    plan = create_plan(client, headers)

    response = client.delete(f"/savings-plans/{plan['id']}", headers=headers)
    assert response.status_code == 204

    assert client.get(f"/savings-plans/{plan['id']}", headers=headers).status_code == 404
    assert client.get("/savings-plans", headers=headers).json() == []


# ---------------------------------------------------------------- «Logrado»


def test_monthly_confirmation_adds_confirmed_amount(client):
    headers = register_and_login(client, "ana@example.com")
    plan = create_plan(client, headers)

    # «Logrado» — este mes pudo ahorrar incluso más de lo planeado
    response = client.post(
        f"/savings-plans/{plan['id']}/entries",
        json={"kind": "monthly", "amount": "320"},
        headers=headers,
    )

    assert response.status_code == 201, response.text
    updated = response.json()
    assert as_decimal(updated["saved_amount"]) == as_decimal("320")
    assert updated["is_current_period_confirmed"] is True
    entry = updated["entries"][0]
    assert entry["kind"] == "monthly"
    assert entry["period"] == current_period()


def test_monthly_confirmation_once_per_month(client):
    headers = register_and_login(client, "ana@example.com")
    plan = create_plan(client, headers)
    client.post(
        f"/savings-plans/{plan['id']}/entries",
        json={"kind": "monthly", "amount": "300"},
        headers=headers,
    )

    response = client.post(
        f"/savings-plans/{plan['id']}/entries",
        json={"kind": "monthly", "amount": "300"},
        headers=headers,
    )

    assert response.status_code == 400
    assert "confirmado" in response.json()["detail"].lower()


def test_monthly_confirmation_with_zero_marks_month(client):
    """«No lo logré» sin nada ahorrado: el mes queda cerrado con 0."""
    headers = register_and_login(client, "ana@example.com")
    plan = create_plan(client, headers)

    response = client.post(
        f"/savings-plans/{plan['id']}/entries",
        json={"kind": "monthly", "amount": "0"},
        headers=headers,
    )

    assert response.status_code == 201, response.text
    updated = response.json()
    assert as_decimal(updated["saved_amount"]) == as_decimal("0")
    assert updated["is_current_period_confirmed"] is True


def test_monthly_confirmation_rejects_negative_amount(client):
    headers = register_and_login(client, "ana@example.com")
    plan = create_plan(client, headers)

    response = client.post(
        f"/savings-plans/{plan['id']}/entries",
        json={"kind": "monthly", "amount": "-50"},
        headers=headers,
    )

    assert response.status_code == 400


def test_monthly_confirmation_for_past_month(client):
    headers = register_and_login(client, "ana@example.com")
    plan = create_plan(client, headers)
    past = shift_period(current_period(), -1)

    response = client.post(
        f"/savings-plans/{plan['id']}/entries",
        json={"kind": "monthly", "amount": "250", "period": past},
        headers=headers,
    )

    assert response.status_code == 201, response.text
    updated = response.json()
    assert as_decimal(updated["saved_amount"]) == as_decimal("250")
    # el mes en curso sigue sin confirmar
    assert updated["is_current_period_confirmed"] is False


def test_monthly_confirmation_rejects_bad_period_format(client):
    headers = register_and_login(client, "ana@example.com")
    plan = create_plan(client, headers)

    response = client.post(
        f"/savings-plans/{plan['id']}/entries",
        json={"kind": "monthly", "amount": "100", "period": "julio-2026"},
        headers=headers,
    )

    assert response.status_code == 422


# ---------------------------------------------------------------- ajustes


def test_adjustments_add_and_subtract_without_period(client):
    headers = register_and_login(client, "ana@example.com")
    plan = create_plan(client, headers, saved="600")

    # encontró dinero con el que no contaba
    response = client.post(
        f"/savings-plans/{plan['id']}/entries",
        json={"kind": "adjustment", "amount": "75.50"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assert as_decimal(response.json()["saved_amount"]) == as_decimal("675.50")

    # un imprevisto: cogió dinero de la hucha, sin justificar nada
    response = client.post(
        f"/savings-plans/{plan['id']}/entries",
        json={"kind": "adjustment", "amount": "-200"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    updated = response.json()
    assert as_decimal(updated["saved_amount"]) == as_decimal("475.50")
    assert all(e["period"] is None for e in updated["entries"] if e["kind"] == "adjustment")
    # los ajustes no cierran el mes
    assert updated["is_current_period_confirmed"] is False


def test_adjustment_cannot_leave_negative_balance(client):
    headers = register_and_login(client, "ana@example.com")
    plan = create_plan(client, headers, saved="100")

    response = client.post(
        f"/savings-plans/{plan['id']}/entries",
        json={"kind": "adjustment", "amount": "-150"},
        headers=headers,
    )

    assert response.status_code == 400
    assert "negativo" in response.json()["detail"].lower()


def test_adjustment_of_zero_is_rejected(client):
    headers = register_and_login(client, "ana@example.com")
    plan = create_plan(client, headers)

    response = client.post(
        f"/savings-plans/{plan['id']}/entries",
        json={"kind": "adjustment", "amount": "0"},
        headers=headers,
    )

    assert response.status_code == 400


# ---------------------------------------------------------------- meta lograda


def test_completed_plan_reports_zero_months(client):
    headers = register_and_login(client, "ana@example.com")
    plan = create_plan(client, headers, target="500", monthly="250", saved="500")

    assert plan["is_completed"] is True
    assert plan["months_to_goal"] == 0
    assert as_decimal(plan["remaining_amount"]) == as_decimal("0")
    assert plan["projected_period"] == current_period()


def test_partial_month_rounds_up(client):
    """1.800 restantes a 250/mes son 7,2 meses: se llega en el octavo."""
    headers = register_and_login(client, "ana@example.com")
    plan = create_plan(client, headers, target="2400", monthly="250", saved="600")

    assert plan["months_to_goal"] == 8
