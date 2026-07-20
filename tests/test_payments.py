from tests.conftest import create_group, make_standard_group, register_and_login


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


def test_borrar_pago_des_salda_y_devuelve_el_balance(client):
    """Des-saldar: al borrar el pago, los balances vuelven a como estaban."""
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
    balances_antes = client.get(f"/groups/{group['id']}/balances", headers=headers).json()

    payment = client.post(
        f"/groups/{group['id']}/payments",
        json={"from_member_id": bea["id"], "to_member_id": owner["id"], "amount": "10"},
        headers=headers,
    ).json()

    response = client.delete(
        f"/groups/{group['id']}/payments/{payment['id']}", headers=headers
    )
    assert response.status_code == 204, response.text
    assert client.get(f"/groups/{group['id']}/payments", headers=headers).json() == []
    balances_despues = client.get(f"/groups/{group['id']}/balances", headers=headers).json()
    assert balances_despues == balances_antes


def test_borrar_pago_requiere_ser_miembro(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)
    payment = client.post(
        f"/groups/{group['id']}/payments",
        json={"from_member_id": bea["id"], "to_member_id": owner["id"], "amount": "10"},
        headers=headers,
    ).json()

    intruso = register_and_login(client, "intruso@example.com", "Intruso")
    response = client.delete(
        f"/groups/{group['id']}/payments/{payment['id']}", headers=intruso
    )
    assert response.status_code == 403


def test_borrar_pago_de_otro_grupo_devuelve_404(client):
    """El pago debe pertenecer al grupo de la ruta, no solo existir."""
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)
    payment = client.post(
        f"/groups/{group['id']}/payments",
        json={"from_member_id": bea["id"], "to_member_id": owner["id"], "amount": "10"},
        headers=headers,
    ).json()

    otro_grupo = create_group(client, headers, name="Otro grupo")
    response = client.delete(
        f"/groups/{otro_grupo['id']}/payments/{payment['id']}", headers=headers
    )
    assert response.status_code == 404


def test_borrar_pago_inexistente_devuelve_404(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)
    response = client.delete(
        f"/groups/{group['id']}/payments/00000000-0000-0000-0000-000000000000",
        headers=headers,
    )
    assert response.status_code == 404


def test_listar_pagos_requiere_ser_miembro(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    group, owner, bea, carlos = make_standard_group(client, headers)
    intruso = register_and_login(client, "intruso@example.com", "Intruso")
    response = client.get(f"/groups/{group['id']}/payments", headers=intruso)
    assert response.status_code == 403
