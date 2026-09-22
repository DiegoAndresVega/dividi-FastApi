"""Derecho de acceso y derecho de borrado (RGPD, artículos 15, 17 y 20).

El borrado no puede ser un DELETE a secas: los gastos de un grupo compartido
son también datos de los demás miembros, y quitarlos descuadraría sus balances.
Lo que se borra es la persona; lo que se conserva son los importes, con el
miembro convertido en «Usuario eliminado».
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import User
from app.security import hash_password
from tests.conftest import as_decimal, register_and_login

CONTRASENA = "password123"


def _crear_grupo_con_beto(client, ana_headers) -> dict:
    """Grupo de Ana (60%) y Beto (40%), enlazado a la cuenta de Beto por email."""
    response = client.post(
        "/groups",
        json={
            "name": "Piso",
            "owner_percentage": "60",
            "members": [
                {
                    "display_name": "Beto",
                    "email": "beto@example.com",
                    "default_percentage": "40",
                }
            ],
        },
        headers=ana_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _gasto(client, headers, group_id, pagador_id, importe="100.00") -> dict:
    response = client.post(
        f"/groups/{group_id}/expenses",
        json={
            "description": "Compra",
            "amount": importe,
            "currency": "EUR",
            "paid_by": pagador_id,
            "split_method": "percentage",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _borrar_cuenta(client, headers, password=CONTRASENA):
    return client.request(
        "DELETE", "/me", json={"password": password}, headers=headers
    )


# --------------------------------------------------------------------------
# Derecho de borrado (artículo 17)
# --------------------------------------------------------------------------


def test_borrar_la_cuenta_exige_la_contrasena(client):
    headers = register_and_login(client, "ana@example.com", name="Ana")

    response = _borrar_cuenta(client, headers, password="la-que-no-es")

    assert response.status_code == 400, response.text
    # y la cuenta sigue en pie
    assert client.get("/me", headers=headers).status_code == 200


def test_borrar_la_cuenta_requiere_autenticacion(client):
    assert client.request("DELETE", "/me", json={"password": CONTRASENA}).status_code == 401


def test_tras_borrarla_el_token_deja_de_valer(client):
    headers = register_and_login(client, "ana@example.com", name="Ana")

    assert _borrar_cuenta(client, headers).status_code == 204

    assert client.get("/me", headers=headers).status_code == 401


def test_tras_borrarla_no_se_puede_entrar_con_la_contrasena_de_antes(client):
    headers = register_and_login(client, "ana@example.com", name="Ana")
    _borrar_cuenta(client, headers)

    response = client.post(
        "/auth/login", data={"username": "ana@example.com", "password": CONTRASENA}
    )

    assert response.status_code == 401, response.text


def test_el_email_queda_libre_para_volver_a_registrarse(client):
    headers = register_and_login(client, "ana@example.com", name="Ana")
    _borrar_cuenta(client, headers)

    response = client.post(
        "/auth/register",
        json={"email": "ana@example.com", "password": CONTRASENA, "name": "Ana"},
    )

    assert response.status_code == 201, response.text


def test_borrar_la_cuenta_anonimiza_al_miembro_sin_tocar_los_importes(client):
    ana = register_and_login(client, "ana@example.com", name="Ana")
    beto = register_and_login(client, "beto@example.com", name="Beto")
    grupo = _crear_grupo_con_beto(client, ana)
    ana_miembro = next(m for m in grupo["members"] if m["display_name"] == "Ana")
    _gasto(client, ana, grupo["id"], ana_miembro["id"], "100.00")
    balances_antes = client.get(f"/groups/{grupo['id']}/balances", headers=beto).json()

    assert _borrar_cuenta(client, ana).status_code == 204

    # Beto conserva el grupo, con los mismos números
    balances_despues = client.get(
        f"/groups/{grupo['id']}/balances", headers=beto
    ).json()
    assert {b["member_id"]: as_decimal(b["balance"]) for b in balances_despues} == {
        b["member_id"]: as_decimal(b["balance"]) for b in balances_antes
    }
    # pero Ana ya no es una persona ahí: ni nombre, ni email, ni cuenta
    detalle = client.get(f"/groups/{grupo['id']}", headers=beto).json()
    fantasma = next(m for m in detalle["members"] if m["id"] == ana_miembro["id"])
    assert fantasma["display_name"] == "Usuario eliminado"
    assert fantasma["user_id"] is None
    assert fantasma["invited_email"] is None


def test_el_gasto_que_creo_sigue_en_el_grupo(client):
    ana = register_and_login(client, "ana@example.com", name="Ana")
    beto = register_and_login(client, "beto@example.com", name="Beto")
    grupo = _crear_grupo_con_beto(client, ana)
    ana_miembro = next(m for m in grupo["members"] if m["display_name"] == "Ana")
    gasto = _gasto(client, ana, grupo["id"], ana_miembro["id"], "100.00")

    _borrar_cuenta(client, ana)

    gastos = client.get(f"/groups/{grupo['id']}/expenses", headers=beto).json()
    assert [g["id"] for g in gastos] == [gasto["id"]]
    assert as_decimal(gastos[0]["amount"]) == Decimal("100.00")


def test_borrar_la_cuenta_se_lleva_lo_que_solo_era_suyo(client):
    headers = register_and_login(client, "ana@example.com", name="Ana")
    client.post(
        "/me/expenses",
        json={"description": "Café", "amount": "2.50"},
        headers=headers,
    )
    client.put(
        "/me/finances",
        json={
            "monthly_income": "1800.00",
            "budgets": [{"category": "Comida", "limit_amount": "300.00"}],
        },
        headers=headers,
    )
    client.post(
        "/savings-plans",
        json={"name": "Viaje", "target_amount": "1000", "monthly_amount": "100"},
        headers=headers,
    )

    _borrar_cuenta(client, headers)

    # al registrarse de nuevo con el mismo email, la cuenta empieza vacía
    nuevos = register_and_login(client, "ana@example.com", name="Ana")
    assert client.get("/me/expenses", headers=nuevos).json() == []
    assert client.get("/savings-plans", headers=nuevos).json() == []
    finanzas = client.get("/me/finances", headers=nuevos).json()
    assert finanzas["monthly_income"] is None
    assert finanzas["budgets"] == []


def test_borrar_la_cuenta_deshace_las_amistades(client):
    ana = register_and_login(client, "ana@example.com", name="Ana")
    beto = register_and_login(client, "beto@example.com", name="Beto")
    client.post("/friends/requests", json={"email": "beto@example.com"}, headers=ana)
    solicitud = client.get("/friends/requests", headers=beto).json()[0]
    client.post(f"/friends/requests/{solicitud['id']}/accept", headers=beto)
    assert len(client.get("/friends", headers=beto).json()) == 1

    _borrar_cuenta(client, ana)

    assert client.get("/friends", headers=beto).json() == []


def test_borrar_la_cuenta_se_lleva_sus_notificaciones(client):
    ana = register_and_login(client, "ana@example.com", name="Ana")
    # la solicitud de Beto le deja una notificación a Ana, que es dato de Ana
    beto = register_and_login(client, "beto@example.com", name="Beto")
    client.post("/friends/requests", json={"email": "ana@example.com"}, headers=beto)
    assert client.get("/notifications", headers=ana).json() != []

    _borrar_cuenta(client, ana)

    nuevos = register_and_login(client, "ana@example.com", name="Ana")
    assert client.get("/notifications", headers=nuevos).json() == []


# --------------------------------------------------------------------------
# Derecho de acceso y portabilidad (artículos 15 y 20)
# --------------------------------------------------------------------------


def test_el_export_requiere_autenticacion(client):
    assert client.get("/me/export").status_code == 401


def test_el_export_trae_el_perfil_y_lo_personal(client):
    headers = register_and_login(client, "ana@example.com", name="Ana")
    client.post(
        "/me/expenses", json={"description": "Café", "amount": "2.50"}, headers=headers
    )
    client.post(
        "/savings-plans",
        json={"name": "Viaje", "target_amount": "1000", "monthly_amount": "100"},
        headers=headers,
    )

    response = client.get("/me/export", headers=headers)

    assert response.status_code == 200, response.text
    datos = response.json()
    assert datos["perfil"]["email"] == "ana@example.com"
    assert datos["perfil"]["name"] == "Ana"
    assert [g["description"] for g in datos["gastos_personales"]] == ["Café"]
    assert [p["name"] for p in datos["planes_de_ahorro"]] == ["Viaje"]


def test_el_export_no_lleva_el_hash_de_la_contrasena(client):
    headers = register_and_login(client, "ana@example.com", name="Ana")

    response = client.get("/me/export", headers=headers)

    assert response.status_code == 200, response.text
    crudo = response.text
    assert "hashed_password" not in crudo
    assert "$2b$" not in crudo


def test_el_export_trae_los_grupos_y_sus_gastos(client):
    ana = register_and_login(client, "ana@example.com", name="Ana")
    register_and_login(client, "beto@example.com", name="Beto")
    grupo = _crear_grupo_con_beto(client, ana)
    ana_miembro = next(m for m in grupo["members"] if m["display_name"] == "Ana")
    _gasto(client, ana, grupo["id"], ana_miembro["id"], "100.00")

    datos = client.get("/me/export", headers=ana).json()

    exportado = next(g for g in datos["grupos"] if g["name"] == "Piso")
    assert [g["description"] for g in exportado["gastos"]] == ["Compra"]
    assert as_decimal(exportado["gastos"][0]["amount"]) == Decimal("100.00")


def test_el_export_no_se_lleva_lo_personal_de_otros(client):
    ana = register_and_login(client, "ana@example.com", name="Ana")
    beto = register_and_login(client, "beto@example.com", name="Beto")
    client.post(
        "/me/expenses",
        json={"description": "Secreto de Beto", "amount": "9.99"},
        headers=beto,
    )

    response = client.get("/me/export", headers=ana)

    assert response.status_code == 200, response.text
    assert "Secreto de Beto" not in response.text


def test_quien_reutilice_el_email_no_hereda_el_grupo(client):
    """El registro vincula miembros pendientes por `invited_email` (auth.py).

    Si el borrado dejara ese email puesto, la siguiente persona que se
    registrase con la misma dirección entraría en los grupos de la anterior.
    """
    ana = register_and_login(client, "ana@example.com", name="Ana")
    register_and_login(client, "beto@example.com", name="Beto")
    grupo = _crear_grupo_con_beto(client, ana)

    _borrar_cuenta(client, ana)
    otra = register_and_login(client, "ana@example.com", name="Otra Ana")

    assert client.get("/groups", headers=otra).json() == []
    assert client.get(f"/groups/{grupo['id']}", headers=otra).status_code in (403, 404)


# --------------------------------------------------------------------------
# Restos que dejaba el primer borrado (revisión de seguridad del 2026-09-22)
# --------------------------------------------------------------------------


@pytest.fixture
def invite_only():
    settings.require_invite = True
    yield
    settings.require_invite = False


def test_el_borrado_quita_su_email_de_la_invitacion_que_uso(client, invite_only):
    """Quien invitó ve el email del invitado en `GET /invitations`.

    Si el borrado no lo vacía, la dirección de la persona borrada se queda ahí
    para siempre y su invitador la sigue viendo. Vaciarlo no reabre el código:
    `validate_code` corta en `is_used` antes de mirar el email.
    """
    fundador = register_and_login(client, "fundador@example.com", name="Fundador")
    invitacion = client.post(
        "/invitations", json={"email": "ana@example.com"}, headers=fundador
    ).json()
    client.post(
        "/auth/register",
        json={
            "email": "ana@example.com",
            "password": CONTRASENA,
            "name": "Ana",
            "invite_code": invitacion["code"],
        },
    )
    ana = client.post(
        "/auth/login", data={"username": "ana@example.com", "password": CONTRASENA}
    ).json()
    ana_headers = {"Authorization": f"Bearer {ana['access_token']}"}

    _borrar_cuenta(client, ana_headers)

    listadas = client.get("/invitations", headers=fundador)
    assert "ana@example.com" not in listadas.text
    # y el código sigue sin poder reutilizarse
    reintento = client.post(
        "/auth/register",
        json={
            "email": "otra@example.com",
            "password": CONTRASENA,
            "name": "Otra",
            "invite_code": invitacion["code"],
        },
    )
    assert reintento.status_code == 403


def test_una_cuenta_borrada_no_puede_hacer_login(client, db_session):
    """Defensa en profundidad: hoy la lápida lleva una contraseña aleatoria que
    nadie conoce, pero quien pueda escribir en la base (o el script de reseteo)
    podría ponerle una conocida. El login tiene que mirar `deleted_at` igual
    que lo mira `get_current_user`."""
    headers = register_and_login(client, "ana@example.com", name="Ana")
    _borrar_cuenta(client, headers)
    lapida = db_session.scalar(select(User).where(User.deleted_at.is_not(None)))
    lapida.hashed_password = hash_password(CONTRASENA)
    email_de_la_lapida = lapida.email
    db_session.commit()

    response = client.post(
        "/auth/login",
        data={"username": email_de_la_lapida, "password": CONTRASENA},
    )

    assert response.status_code == 401, response.text
