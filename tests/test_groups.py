from tests.conftest import (
    add_member,
    as_decimal,
    create_group,
    make_standard_group,
    register_and_login,
)


def test_crear_grupo_añade_al_creador_como_admin_al_100(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group = create_group(client, headers)

    assert group["name"] == "Viaje"
    assert group["default_currency"] == "EUR"
    assert len(group["members"]) == 1
    owner = group["members"][0]
    assert owner["role"] == "admin"
    assert as_decimal(owner["default_percentage"]) == 100


def test_listar_solo_grupos_propios(client):
    ana = register_and_login(client, "ana@example.com", "Ana")
    otro = register_and_login(client, "otro@example.com", "Otro")
    create_group(client, ana, name="Grupo de Ana")
    create_group(client, otro, name="Grupo de Otro")

    groups = client.get("/groups", headers=ana).json()
    assert [g["name"] for g in groups] == ["Grupo de Ana"]


def test_detalle_de_grupo_requiere_ser_miembro(client):
    ana = register_and_login(client, "ana@example.com", "Ana")
    intruso = register_and_login(client, "intruso@example.com", "Intruso")
    group = create_group(client, ana)

    assert client.get(f"/groups/{group['id']}", headers=ana).status_code == 200
    assert client.get(f"/groups/{group['id']}", headers=intruso).status_code == 403


def test_editar_grupo(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group = create_group(client, headers)
    response = client.patch(
        f"/groups/{group['id']}",
        json={"name": "Viaje a Roma", "default_currency": "USD"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Viaje a Roma"
    assert response.json()["default_currency"] == "USD"


def test_borrar_grupo_solo_admin(client):
    ana = register_and_login(client, "ana@example.com", "Ana")
    bea = register_and_login(client, "bea@example.com", "Bea")
    group = create_group(client, ana)
    owner = group["members"][0]
    client.post(
        f"/groups/{group['id']}/members",
        json={
            "email": "bea@example.com",
            "default_percentage": "50",
            "rebalance": {owner["id"]: "50"},
        },
        headers=ana,
    )

    assert client.delete(f"/groups/{group['id']}", headers=bea).status_code == 403
    assert client.delete(f"/groups/{group['id']}", headers=ana).status_code == 204
    assert client.get(f"/groups/{group['id']}", headers=ana).status_code == 404


def test_borrar_grupo_con_gastos_y_pagos_arrastra_todo(client):
    """Un grupo creado por error o ya saldado se borra con toda su actividad."""
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)

    client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Cena",
            "amount": "30",
            "paid_by": owner["id"],
            "split_method": "equal",
        },
        headers=headers,
    )
    client.post(
        f"/groups/{group['id']}/payments",
        json={"from_member_id": bea["id"], "to_member_id": owner["id"], "amount": "10"},
        headers=headers,
    )

    assert client.delete(f"/groups/{group['id']}", headers=headers).status_code == 204
    assert client.get(f"/groups/{group['id']}", headers=headers).status_code == 404
    assert group["id"] not in [g["id"] for g in client.get("/groups", headers=headers).json()]


def test_añadir_miembro_sin_rebalance_que_rompe_el_100_falla(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group = create_group(client, headers)
    response = client.post(
        f"/groups/{group['id']}/members",
        json={"display_name": "Bea", "default_percentage": "30"},
        headers=headers,
    )
    assert response.status_code == 400
    assert "sumar 100" in response.json()["detail"]


def test_añadir_miembro_con_rebalance_correcto(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)

    detail = client.get(f"/groups/{group['id']}", headers=headers).json()
    percentages = {
        m["display_name"]: as_decimal(m["default_percentage"]) for m in detail["members"]
    }
    assert percentages == {"Ana": 50, "Bea": 30, "Carlos": 20}


def test_añadir_miembro_requiere_admin(client):
    ana = register_and_login(client, "ana@example.com", "Ana")
    bea = register_and_login(client, "bea@example.com", "Bea")
    group = create_group(client, ana)
    owner = group["members"][0]
    client.post(
        f"/groups/{group['id']}/members",
        json={
            "email": "bea@example.com",
            "default_percentage": "50",
            "rebalance": {owner["id"]: "50"},
        },
        headers=ana,
    )
    response = client.post(
        f"/groups/{group['id']}/members",
        json={"display_name": "Carlos", "default_percentage": "0"},
        headers=bea,
    )
    assert response.status_code == 403


def test_añadir_email_duplicado_devuelve_409(client):
    ana = register_and_login(client, "ana@example.com", "Ana")
    group = create_group(client, ana)
    owner = group["members"][0]
    payload = {
        "email": "bea@example.com",
        "default_percentage": "50",
        "rebalance": {owner["id"]: "50"},
    }
    assert (
        client.post(f"/groups/{group['id']}/members", json=payload, headers=ana).status_code
        == 201
    )
    assert (
        client.post(f"/groups/{group['id']}/members", json=payload, headers=ana).status_code
        == 409
    )


def test_editar_porcentaje_con_rebalance(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)

    response = client.patch(
        f"/groups/{group['id']}/members/{bea['id']}",
        json={
            "default_percentage": "40",
            "rebalance": {owner["id"]: "40", carlos["id"]: "20"},
        },
        headers=headers,
    )
    assert response.status_code == 200
    assert as_decimal(response.json()["default_percentage"]) == 40


def test_editar_porcentaje_rompiendo_el_100_falla(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)

    response = client.patch(
        f"/groups/{group['id']}/members/{bea['id']}",
        json={"default_percentage": "99"},
        headers=headers,
    )
    assert response.status_code == 400


def test_no_se_puede_quitar_el_ultimo_admin(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)

    response = client.patch(
        f"/groups/{group['id']}/members/{owner['id']}",
        json={"role": "member"},
        headers=headers,
    )
    assert response.status_code == 400


def test_eliminar_miembro_sin_actividad_con_rebalance(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)

    response = client.request(
        "DELETE",
        f"/groups/{group['id']}/members/{carlos['id']}",
        json={"rebalance": {owner["id"]: "60", bea["id"]: "40"}},
        headers=headers,
    )
    assert response.status_code == 204
    detail = client.get(f"/groups/{group['id']}", headers=headers).json()
    assert len(detail["members"]) == 2


def test_eliminar_miembro_con_gastos_falla(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)
    client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Cena",
            "amount": "30",
            "paid_by": carlos["id"],
            "split_method": "equal",
        },
        headers=headers,
    )
    response = client.request(
        "DELETE",
        f"/groups/{group['id']}/members/{carlos['id']}",
        json={"rebalance": {owner["id"]: "60", bea["id"]: "40"}},
        headers=headers,
    )
    assert response.status_code == 400
    assert "gastos o pagos" in response.json()["detail"]
