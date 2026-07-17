from decimal import Decimal

from tests.conftest import (
    as_decimal,
    create_group,
    make_standard_group,
    register_and_login,
)


def splits_by_member(expense: dict) -> dict:
    return {s["group_member_id"]: as_decimal(s["computed_amount"]) for s in expense["splits"]}


def test_gasto_equal_sin_splits_reparte_entre_todo_el_grupo(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)

    response = client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Cena",
            "amount": "10",
            "paid_by": owner["id"],
            "split_method": "equal",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    expense = response.json()
    amounts = splits_by_member(expense)
    assert amounts[owner["id"]] == Decimal("3.33")
    assert amounts[bea["id"]] == Decimal("3.33")
    assert amounts[carlos["id"]] == Decimal("3.34")
    assert expense["currency"] == "EUR"


def test_gasto_acepta_categorias_nuevas(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)

    categorias = (
        "supermercado", "gasolina", "casa", "bar",
        "recibos", "telefono", "viajes", "membresia",
    )
    for categoria in categorias:
        response = client.post(
            f"/groups/{group['id']}/expenses",
            json={
                "description": f"Gasto {categoria}",
                "amount": "10",
                "paid_by": owner["id"],
                "split_method": "equal",
                "category": categoria,
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        expense = response.json()
        assert expense["category"] == categoria
        assert expense["category_icon"] is None


def test_gasto_con_categoria_personalizada_y_emoji(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)

    response = client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Recibo del agua",
            "amount": "30",
            "paid_by": owner["id"],
            "split_method": "equal",
            # el nombre se normaliza (espacios fuera, minúsculas)
            "category": "  Agua ",
            "category_icon": "💧",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    expense = response.json()
    assert expense["category"] == "agua"
    assert expense["category_icon"] == "💧"

    # y el filtro por categoría también funciona con las inventadas
    listado = client.get(
        f"/groups/{group['id']}/expenses?category=agua", headers=headers
    ).json()
    assert [g["id"] for g in listado] == [expense["id"]]


def test_editar_categoria_personalizada_y_volver_a_predefinida(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)

    expense = client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Cuota gimnasio",
            "amount": "45",
            "paid_by": owner["id"],
            "split_method": "equal",
            "category": "gimnasio",
            "category_icon": "🏋️",
        },
        headers=headers,
    ).json()

    # al volver a una predefinida, el emoji se limpia explícitamente
    response = client.patch(
        f"/groups/{group['id']}/expenses/{expense['id']}",
        json={"category": "membresia", "category_icon": None},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    editado = response.json()
    assert editado["category"] == "membresia"
    assert editado["category_icon"] is None


def test_categoria_invalida_rechazada(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)

    base = {
        "description": "Gasto raro",
        "amount": "10",
        "paid_by": owner["id"],
        "split_method": "equal",
    }
    for extra in (
        {"category": ""},
        {"category": "   "},
        {"category": "x" * 31},
        {"category": "agua", "category_icon": "x" * 21},
    ):
        response = client.post(
            f"/groups/{group['id']}/expenses", json={**base, **extra}, headers=headers
        )
        assert response.status_code == 422, extra


def test_gasto_percentage_sin_splits_usa_defaults_del_grupo(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)

    response = client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Hotel",
            "amount": "100",
            "paid_by": owner["id"],
            "split_method": "percentage",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    amounts = splits_by_member(response.json())
    assert amounts[owner["id"]] == Decimal("50")
    assert amounts[bea["id"]] == Decimal("30")
    assert amounts[carlos["id"]] == Decimal("20")


def test_gasto_percentage_con_override(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)

    response = client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Entradas",
            "amount": "80",
            "paid_by": bea["id"],
            "split_method": "percentage",
            "splits": [
                {"group_member_id": owner["id"], "percentage": "25"},
                {"group_member_id": bea["id"], "percentage": "75"},
            ],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    amounts = splits_by_member(response.json())
    assert amounts == {owner["id"]: Decimal("20"), bea["id"]: Decimal("60")}


def test_gasto_percentage_que_no_suma_100_devuelve_400(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)

    response = client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Mal reparto",
            "amount": "80",
            "paid_by": owner["id"],
            "split_method": "percentage",
            "splits": [
                {"group_member_id": owner["id"], "percentage": "25"},
                {"group_member_id": bea["id"], "percentage": "25"},
            ],
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert "sumar 100" in response.json()["detail"]


def test_gasto_exact(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)

    response = client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Compra",
            "amount": "45.50",
            "paid_by": owner["id"],
            "split_method": "exact",
            "splits": [
                {"group_member_id": owner["id"], "exact_amount": "20.50"},
                {"group_member_id": bea["id"], "exact_amount": "25.00"},
            ],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    amounts = splits_by_member(response.json())
    assert amounts == {owner["id"]: Decimal("20.50"), bea["id"]: Decimal("25.00")}


def test_gasto_exact_que_no_cuadra_devuelve_400(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)

    response = client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Compra",
            "amount": "45.50",
            "paid_by": owner["id"],
            "split_method": "exact",
            "splits": [
                {"group_member_id": owner["id"], "exact_amount": "20"},
                {"group_member_id": bea["id"], "exact_amount": "20"},
            ],
        },
        headers=headers,
    )
    assert response.status_code == 400


def test_gasto_exact_sin_splits_devuelve_400(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)

    response = client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Compra",
            "amount": "45.50",
            "paid_by": owner["id"],
            "split_method": "exact",
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert "splits" in response.json()["detail"]


def test_gasto_shares(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)

    response = client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Gasolina",
            "amount": "60",
            "paid_by": carlos["id"],
            "split_method": "shares",
            "splits": [
                {"group_member_id": owner["id"], "shares": 2},
                {"group_member_id": bea["id"], "shares": 1},
            ],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    amounts = splits_by_member(response.json())
    assert amounts == {owner["id"]: Decimal("40"), bea["id"]: Decimal("20")}


def test_paid_by_de_otro_grupo_devuelve_400(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)
    otro_grupo = create_group(client, headers, name="Otro")
    otro_member = otro_grupo["members"][0]

    response = client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Cena",
            "amount": "30",
            "paid_by": otro_member["id"],
            "split_method": "equal",
        },
        headers=headers,
    )
    assert response.status_code == 400


def test_moneda_distinta_a_la_del_grupo_devuelve_400(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)

    response = client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Cena",
            "amount": "30",
            "currency": "USD",
            "paid_by": owner["id"],
            "split_method": "equal",
        },
        headers=headers,
    )
    assert response.status_code == 400


def test_filtro_por_categoria(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)
    for description, category in [
        ("Cena", "comida"),
        ("Taxi", "transporte"),
        ("Tapas", "comida"),
    ]:
        client.post(
            f"/groups/{group['id']}/expenses",
            json={
                "description": description,
                "amount": "10",
                "category": category,
                "paid_by": owner["id"],
                "split_method": "equal",
            },
            headers=headers,
        )

    response = client.get(
        f"/groups/{group['id']}/expenses", params={"category": "comida"}, headers=headers
    )
    assert response.status_code == 200
    assert sorted(e["description"] for e in response.json()) == ["Cena", "Tapas"]


def test_editar_importe_recalcula_splits(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)
    expense = client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Hotel",
            "amount": "100",
            "paid_by": owner["id"],
            "split_method": "percentage",
        },
        headers=headers,
    ).json()

    response = client.patch(
        f"/groups/{group['id']}/expenses/{expense['id']}",
        json={"amount": "200"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    amounts = splits_by_member(response.json())
    assert amounts[owner["id"]] == Decimal("100")
    assert amounts[bea["id"]] == Decimal("60")
    assert amounts[carlos["id"]] == Decimal("40")


def test_member_no_puede_borrar_gasto_ajeno_pero_admin_si(client):
    ana = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea_member, carlos = make_standard_group(client, ana)

    # añadimos a Dora con cuenta real como member (0%, sin tocar el resto)
    detail = client.get(f"/groups/{group['id']}", headers=ana).json()
    rebalance = {m["id"]: m["default_percentage"] for m in detail["members"]}
    dora_headers = register_and_login(client, "dora@example.com", "Dora")
    dora = client.post(
        f"/groups/{group['id']}/members",
        json={"email": "dora@example.com", "default_percentage": "0", "rebalance": rebalance},
        headers=ana,
    ).json()

    # Ana (admin) crea un gasto
    gasto_ana = client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Cena",
            "amount": "30",
            "paid_by": owner["id"],
            "split_method": "equal",
        },
        headers=ana,
    ).json()

    # Dora (member) no puede borrar el gasto de Ana
    response = client.delete(
        f"/groups/{group['id']}/expenses/{gasto_ana['id']}", headers=dora_headers
    )
    assert response.status_code == 403

    # Dora crea el suyo y sí puede borrarlo
    gasto_dora = client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Taxi",
            "amount": "10",
            "paid_by": dora["id"],
            "split_method": "equal",
        },
        headers=dora_headers,
    ).json()
    assert (
        client.delete(
            f"/groups/{group['id']}/expenses/{gasto_dora['id']}", headers=dora_headers
        ).status_code
        == 204
    )

    # y Ana (admin) puede borrar cualquier gasto
    assert (
        client.delete(
            f"/groups/{group['id']}/expenses/{gasto_ana['id']}", headers=ana
        ).status_code
        == 204
    )
