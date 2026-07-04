from tests.conftest import make_standard_group, register_and_login


def test_crear_y_listar_pagos(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)

    response = client.post(
        f"/groups/{group['id']}/payments",
        json={
            "from_member_id": bea["id"],
            "to_member_id": owner["id"],
            "amount": "25.50",
            "note": "Bizum",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    payment = response.json()
    assert payment["note"] == "Bizum"

    payments = client.get(f"/groups/{group['id']}/payments", headers=headers).json()
    assert len(payments) == 1
    assert payments[0]["id"] == payment["id"]


def test_pago_a_uno_mismo_devuelve_400(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)
    response = client.post(
        f"/groups/{group['id']}/payments",
        json={"from_member_id": bea["id"], "to_member_id": bea["id"], "amount": "10"},
        headers=headers,
    )
    assert response.status_code == 400


def test_pago_con_miembro_de_otro_grupo_devuelve_400(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)
    otro = register_and_login(client, "otro@example.com", "Otro")
    from tests.conftest import create_group

    otro_grupo = create_group(client, otro, name="Otro grupo")
    ajeno = otro_grupo["members"][0]

    response = client.post(
        f"/groups/{group['id']}/payments",
        json={"from_member_id": ajeno["id"], "to_member_id": owner["id"], "amount": "10"},
        headers=headers,
    )
    assert response.status_code == 400


def test_pago_con_importe_negativo_devuelve_422(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)
    response = client.post(
        f"/groups/{group['id']}/payments",
        json={"from_member_id": bea["id"], "to_member_id": owner["id"], "amount": "-5"},
        headers=headers,
    )
    assert response.status_code == 422


def test_listar_pagos_requiere_ser_miembro(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)
    intruso = register_and_login(client, "intruso@example.com", "Intruso")
    response = client.get(f"/groups/{group['id']}/payments", headers=intruso)
    assert response.status_code == 403
