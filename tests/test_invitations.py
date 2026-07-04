import pytest

from app.config import settings
from tests.conftest import register_and_login


@pytest.fixture
def invite_only():
    """Activa el modo invite-only solo durante el test."""
    settings.require_invite = True
    yield
    settings.require_invite = False


def register(client, email, code=None, name="User"):
    body = {"email": email, "password": "password123", "name": name}
    if code is not None:
        body["invite_code"] = code
    return client.post("/auth/register", json=body)


def test_primer_usuario_es_fundador_sin_codigo(client, invite_only):
    # con la BD vacía, el primer registro no necesita invitación
    assert register(client, "fundador@example.com").status_code == 201


def test_segundo_usuario_sin_codigo_falla(client, invite_only):
    register(client, "fundador@example.com")
    r = register(client, "colado@example.com")
    assert r.status_code == 403
    assert "invitaci" in r.json()["detail"].lower()


def test_flujo_completo_de_invitacion(client, invite_only):
    # el fundador se registra y genera una invitación
    founder = register_and_login(client, "fundador@example.com", "Fundador")
    inv = client.post("/invitations", json={}, headers=founder).json()
    assert inv["code"]
    assert inv["used_by_id"] is None

    # con ese código, un amigo puede registrarse
    assert register(client, "amigo@example.com", code=inv["code"]).status_code == 201

    # y el código queda consumido: no sirve una segunda vez
    r = register(client, "otro@example.com", code=inv["code"])
    assert r.status_code == 403
    assert "utilizado" in r.json()["detail"].lower()


def test_codigo_inexistente_falla(client, invite_only):
    register_and_login(client, "fundador@example.com", "Fundador")
    r = register(client, "amigo@example.com", code="codigo-que-no-existe")
    assert r.status_code == 403
    assert "no existe" in r.json()["detail"].lower()


def test_invitacion_atada_a_email(client, invite_only):
    founder = register_and_login(client, "fundador@example.com", "Fundador")
    inv = client.post(
        "/invitations", json={"email": "bea@example.com"}, headers=founder
    ).json()

    # otro email no puede usarla
    assert register(client, "carlos@example.com", code=inv["code"]).status_code == 403
    # el email correcto sí
    assert register(client, "bea@example.com", code=inv["code"]).status_code == 201


def test_check_publico_de_codigo(client, invite_only):
    founder = register_and_login(client, "fundador@example.com", "Fundador")
    inv = client.post("/invitations", json={}, headers=founder).json()

    ok = client.get(f"/invitations/{inv['code']}/check").json()
    assert ok["valid"] is True

    bad = client.get("/invitations/no-existe/check").json()
    assert bad["valid"] is False
    assert bad["reason"]


def test_revocar_invitacion_no_usada(client, invite_only):
    founder = register_and_login(client, "fundador@example.com", "Fundador")
    inv = client.post("/invitations", json={}, headers=founder).json()

    assert client.delete(f"/invitations/{inv['id']}", headers=founder).status_code == 204
    # ya no es válida
    assert register(client, "amigo@example.com", code=inv["code"]).status_code == 403


def test_no_se_puede_revocar_invitacion_usada(client, invite_only):
    founder = register_and_login(client, "fundador@example.com", "Fundador")
    inv = client.post("/invitations", json={}, headers=founder).json()
    register(client, "amigo@example.com", code=inv["code"])

    assert client.delete(f"/invitations/{inv['id']}", headers=founder).status_code == 400


def test_listar_mis_invitaciones(client, invite_only):
    founder = register_and_login(client, "fundador@example.com", "Fundador")
    client.post("/invitations", json={}, headers=founder)
    client.post("/invitations", json={}, headers=founder)

    invites = client.get("/invitations", headers=founder).json()
    assert len(invites) == 2


def test_crear_invitacion_requiere_login(client, invite_only):
    assert client.post("/invitations", json={}).status_code == 401
