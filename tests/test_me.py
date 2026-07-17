"""Tests del perfil propio (M1): GET/PATCH /me y cambio de contraseña."""

from tests.conftest import register_and_login


def test_get_me_returns_own_profile(client):
    headers = register_and_login(client, "ana@example.com", name="Ana")

    response = client.get("/me", headers=headers)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["email"] == "ana@example.com"
    assert data["name"] == "Ana"
    assert "hashed_password" not in data


def test_me_requires_authentication(client):
    assert client.get("/me").status_code == 401


def test_patch_me_updates_name(client):
    headers = register_and_login(client, "ana@example.com", name="Ana")

    response = client.patch("/me", json={"name": "Ana María"}, headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Ana María"
    # y queda persistido
    assert client.get("/me", headers=headers).json()["name"] == "Ana María"


def test_patch_me_rejects_empty_name(client):
    headers = register_and_login(client, "ana@example.com")

    response = client.patch("/me", json={"name": ""}, headers=headers)

    assert response.status_code == 422


def test_patch_me_without_fields_changes_nothing(client):
    headers = register_and_login(client, "ana@example.com", name="Ana")

    response = client.patch("/me", json={}, headers=headers)

    assert response.status_code == 200
    assert response.json()["name"] == "Ana"


def test_change_password_and_login_with_new_one(client):
    headers = register_and_login(client, "ana@example.com")

    response = client.post(
        "/me/password",
        json={"current_password": "password123", "new_password": "nueva-clave-9"},
        headers=headers,
    )
    assert response.status_code == 204, response.text

    # la contraseña vieja deja de valer
    old_login = client.post(
        "/auth/login", data={"username": "ana@example.com", "password": "password123"}
    )
    assert old_login.status_code == 401

    # y la nueva funciona
    new_login = client.post(
        "/auth/login", data={"username": "ana@example.com", "password": "nueva-clave-9"}
    )
    assert new_login.status_code == 200, new_login.text


def test_change_password_rejects_wrong_current(client):
    headers = register_and_login(client, "ana@example.com")

    response = client.post(
        "/me/password",
        json={"current_password": "equivocada99", "new_password": "nueva-clave-9"},
        headers=headers,
    )

    assert response.status_code == 400
    assert "actual" in response.json()["detail"].lower()


def test_change_password_rejects_short_new_password(client):
    headers = register_and_login(client, "ana@example.com")

    response = client.post(
        "/me/password",
        json={"current_password": "password123", "new_password": "corta"},
        headers=headers,
    )

    assert response.status_code == 422
