"""Amigos (solicitud + aceptar), centro de notificaciones y los avisos que
disparan (te añadieron a un grupo, aceptaron tu solicitud)."""

from tests.conftest import create_group, register_and_login


def _headers(client, email, name):
    return register_and_login(client, email, name)


# ------------------------------------------------------------- solicitudes


def test_friend_request_full_flow(client):
    ana = _headers(client, "ana@example.com", "Ana")
    beto = _headers(client, "beto@example.com", "Beto")

    # Ana envía solicitud a Beto
    r = client.post("/friends/requests", json={"email": "beto@example.com"}, headers=ana)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "pending"

    # Beto ve la solicitud entrante
    r = client.get("/friends/requests", headers=beto)
    assert r.status_code == 200
    requests = r.json()
    assert len(requests) == 1
    assert requests[0]["from_name"] == "Ana"
    request_id = requests[0]["id"]

    # Beto la acepta
    r = client.post(f"/friends/requests/{request_id}/accept", headers=beto)
    assert r.status_code == 200

    # ahora son amigos por ambos lados
    for headers, amigo in ((ana, "Beto"), (beto, "Ana")):
        r = client.get("/friends", headers=headers)
        assert r.status_code == 200
        friends = r.json()
        assert len(friends) == 1
        assert friends[0]["name"] == amigo

    # Ana recibe la novedad de que aceptaron
    r = client.get("/notifications", headers=ana)
    tipos = [n["type"] for n in r.json()]
    assert "friend_accepted" in tipos


def test_friend_request_to_unknown_email_404(client):
    ana = _headers(client, "ana@example.com", "Ana")
    r = client.post(
        "/friends/requests", json={"email": "fantasma@example.com"}, headers=ana
    )
    assert r.status_code == 404


def test_friend_request_to_self_400(client):
    ana = _headers(client, "ana@example.com", "Ana")
    r = client.post("/friends/requests", json={"email": "ana@example.com"}, headers=ana)
    assert r.status_code == 400


def test_duplicate_friend_request_409(client):
    ana = _headers(client, "ana@example.com", "Ana")
    _headers(client, "beto@example.com", "Beto")
    client.post("/friends/requests", json={"email": "beto@example.com"}, headers=ana)
    r = client.post("/friends/requests", json={"email": "beto@example.com"}, headers=ana)
    assert r.status_code == 409


def test_mutual_request_auto_accepts(client):
    ana = _headers(client, "ana@example.com", "Ana")
    beto = _headers(client, "beto@example.com", "Beto")
    client.post("/friends/requests", json={"email": "beto@example.com"}, headers=ana)
    # Beto envía a Ana sin saber que ya tenía una pendiente: se acepta sola
    r = client.post("/friends/requests", json={"email": "ana@example.com"}, headers=beto)
    assert r.status_code == 201
    assert r.json()["status"] == "accepted"
    assert len(client.get("/friends", headers=ana).json()) == 1


# ----------------------------------------------------------- notificaciones


def test_notifications_unread_count_and_mark_read(client):
    ana = _headers(client, "ana@example.com", "Ana")
    beto = _headers(client, "beto@example.com", "Beto")
    client.post("/friends/requests", json={"email": "beto@example.com"}, headers=ana)

    r = client.get("/notifications/unread-count", headers=beto)
    assert r.json()["unread"] == 1

    r = client.post("/notifications/read-all", headers=beto)
    assert r.status_code == 204
    assert client.get("/notifications/unread-count", headers=beto).json()["unread"] == 0


# ------------------------------------------ añadir amigo a un grupo + aviso


def _befriend(client, a_headers, b_headers, b_email):
    client.post("/friends/requests", json={"email": b_email}, headers=a_headers)
    req_id = client.get("/friends/requests", headers=b_headers).json()[0]["id"]
    client.post(f"/friends/requests/{req_id}/accept", headers=b_headers)


def test_add_friend_to_group_notifies_and_joins(client):
    ana = _headers(client, "ana@example.com", "Ana")
    beto = _headers(client, "beto@example.com", "Beto")
    _befriend(client, ana, beto, "beto@example.com")

    beto_id = client.get("/friends", headers=ana).json()[0]["user_id"]
    group = create_group(client, ana, name="Piso")

    r = client.post(
        f"/groups/{group['id']}/members",
        json={"user_id": beto_id, "default_percentage": "40", "rebalance": {
            group["members"][0]["id"]: "60"
        }},
        headers=ana,
    )
    assert r.status_code == 201, r.text
    assert r.json()["user_id"] == beto_id

    # Beto ahora ve el grupo entre los suyos
    grupos_beto = client.get("/groups", headers=beto).json()
    assert any(g["id"] == group["id"] for g in grupos_beto)

    # y le llegó la novedad
    tipos = [n["type"] for n in client.get("/notifications", headers=beto).json()]
    assert "added_to_group" in tipos


def test_add_non_friend_by_user_id_forbidden(client):
    ana = _headers(client, "ana@example.com", "Ana")
    beto = _headers(client, "beto@example.com", "Beto")
    beto_id = client.get("/me", headers=beto).json()["id"]
    group = create_group(client, ana, name="Piso")
    r = client.post(
        f"/groups/{group['id']}/members",
        json={"user_id": beto_id, "default_percentage": "0"},
        headers=ana,
    )
    assert r.status_code == 403


# --------------------------------------------- crear grupo con invitados


def test_create_group_with_guests(client):
    ana = _headers(client, "ana@example.com", "Ana")
    r = client.post(
        "/groups",
        json={
            "name": "Piso nuevo",
            "owner_percentage": "50",
            "members": [
                {"display_name": "Compi 1", "default_percentage": "30"},
                {"display_name": "Compi 2", "default_percentage": "20"},
            ],
        },
        headers=ana,
    )
    assert r.status_code == 201, r.text
    members = r.json()["members"]
    assert len(members) == 3
    porcentajes = sorted(float(m["default_percentage"]) for m in members)
    assert porcentajes == [20.0, 30.0, 50.0]


def test_create_group_with_guests_wrong_sum_400(client):
    ana = _headers(client, "ana@example.com", "Ana")
    r = client.post(
        "/groups",
        json={
            "name": "Piso",
            "owner_percentage": "50",
            "members": [{"display_name": "Compi", "default_percentage": "30"}],
        },
        headers=ana,
    )
    assert r.status_code == 400


def test_create_group_owner_percentage_defaults_to_remainder(client):
    ana = _headers(client, "ana@example.com", "Ana")
    r = client.post(
        "/groups",
        json={
            "name": "Piso",
            "members": [{"display_name": "Compi", "default_percentage": "30"}],
        },
        headers=ana,
    )
    assert r.status_code == 201, r.text
    owner = next(m for m in r.json()["members"] if m["role"] == "admin")
    assert float(owner["default_percentage"]) == 70.0


def test_create_group_guest_with_registered_email_is_linked_and_notified(client):
    ana = _headers(client, "ana@example.com", "Ana")
    _headers(client, "beto@example.com", "Beto")
    r = client.post(
        "/groups",
        json={
            "name": "Piso",
            "owner_percentage": "50",
            "members": [
                {
                    "display_name": "Beto",
                    "email": "beto@example.com",
                    "default_percentage": "50",
                }
            ],
        },
        headers=ana,
    )
    assert r.status_code == 201, r.text
    beto_member = next(m for m in r.json()["members"] if m["display_name"] == "Beto")
    assert beto_member["user_id"] is not None
