from tests.conftest import add_member, create_group, register_and_login


def test_register_devuelve_usuario_sin_password(client):
    response = client.post(
        "/auth/register",
        json={"email": "ana@example.com", "password": "password123", "name": "Ana"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "ana@example.com"
    assert data["name"] == "Ana"
    assert "password" not in data
    assert "hashed_password" not in data


def test_register_email_duplicado_devuelve_409(client):
    payload = {"email": "ana@example.com", "password": "password123", "name": "Ana"}
    assert client.post("/auth/register", json=payload).status_code == 201
    assert client.post("/auth/register", json=payload).status_code == 409


def test_register_password_corta_devuelve_422(client):
    response = client.post(
        "/auth/register",
        json={"email": "ana@example.com", "password": "corta", "name": "Ana"},
    )
    assert response.status_code == 422


def test_login_correcto_devuelve_tokens(client):
    client.post(
        "/auth/register",
        json={"email": "ana@example.com", "password": "password123", "name": "Ana"},
    )
    response = client.post(
        "/auth/login", data={"username": "ana@example.com", "password": "password123"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["token_type"] == "bearer"


def test_login_password_incorrecta_devuelve_401(client):
    client.post(
        "/auth/register",
        json={"email": "ana@example.com", "password": "password123", "name": "Ana"},
    )
    response = client.post(
        "/auth/login", data={"username": "ana@example.com", "password": "incorrecta1"}
    )
    assert response.status_code == 401


def test_refresh_devuelve_tokens_nuevos(client):
    client.post(
        "/auth/register",
        json={"email": "ana@example.com", "password": "password123", "name": "Ana"},
    )
    login = client.post(
        "/auth/login", data={"username": "ana@example.com", "password": "password123"}
    ).json()
    response = client.post("/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_refresh_con_access_token_devuelve_401(client):
    client.post(
        "/auth/register",
        json={"email": "ana@example.com", "password": "password123", "name": "Ana"},
    )
    login = client.post(
        "/auth/login", data={"username": "ana@example.com", "password": "password123"}
    ).json()
    response = client.post("/auth/refresh", json={"refresh_token": login["access_token"]})
    assert response.status_code == 401


def test_endpoint_protegido_sin_token_devuelve_401(client):
    assert client.get("/groups").status_code == 401


def test_endpoint_protegido_con_token_invalido_devuelve_401(client):
    response = client.get("/groups", headers={"Authorization": "Bearer no-es-un-jwt"})
    assert response.status_code == 401


def test_invitado_se_vincula_al_registrarse(client):
    # el admin crea un grupo e invita a bea@example.com, que aún no tiene cuenta
    headers = register_and_login(client, "admin@example.com", "Admin")
    group = create_group(client, headers)
    owner = group["members"][0]
    response = client.post(
        f"/groups/{group['id']}/members",
        json={
            "email": "bea@example.com",
            "default_percentage": "50",
            "rebalance": {owner["id"]: "50"},
        },
        headers=headers,
    )
    assert response.status_code == 201
    assert response.json()["user_id"] is None

    # cuando Bea se registra con ese email, la membership queda vinculada
    bea_headers = register_and_login(client, "bea@example.com", "Bea")
    groups = client.get("/groups", headers=bea_headers).json()
    assert [g["id"] for g in groups] == [group["id"]]
