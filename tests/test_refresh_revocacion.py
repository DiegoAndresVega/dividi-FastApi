"""Rotación y revocación de refresh tokens.

El refresh token dura un año, así que sin revocación uno robado vale un año
aunque el dueño siga usando la app con normalidad. Estos tests cubren las tres
piezas: que un token gastado no sirva, que reutilizarlo mate la sesión entera
—porque reutilizarlo es la señal de que alguien lo copió— y que el logout lo
invalide en el servidor y no solo en el móvil.
"""

from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings
from app.services import refresh_token_service


def _registrar(client, email: str = "ana@example.com") -> dict:
    """Registra e inicia sesión. Devuelve el par de tokens del login."""
    response = client.post(
        "/auth/register",
        json={"email": email, "password": "password123", "name": "Ana"},
    )
    assert response.status_code == 201, response.text
    response = client.post(
        "/auth/login", data={"username": email, "password": "password123"}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _refrescar(client, refresh_token: str):
    return client.post("/auth/refresh", json={"refresh_token": refresh_token})


# ------------------------------------------------------------------ rotación


def test_un_refresh_token_ya_usado_devuelve_401(client, monkeypatch):
    monkeypatch.setattr(refresh_token_service, "GRACIA_REUTILIZACION", timedelta(0))
    tokens = _registrar(client)

    primero = _refrescar(client, tokens["refresh_token"])
    assert primero.status_code == 200

    segundo = _refrescar(client, tokens["refresh_token"])
    assert segundo.status_code == 401


def test_el_token_nuevo_de_cada_rotacion_si_sirve(client):
    tokens = _registrar(client)

    # tres rotaciones seguidas: cada una devuelve un token utilizable
    for _ in range(3):
        respuesta = _refrescar(client, tokens["refresh_token"])
        assert respuesta.status_code == 200, respuesta.text
        tokens = respuesta.json()


def test_dos_peticiones_a_la_vez_no_cierran_la_sesion(client):
    """La app pide varias cosas en paralelo y todas refrescan con el mismo token.

    Es la carrera normal de cualquier cliente, no un robo. Ambas tienen que
    salir con un token utilizable.
    """
    tokens = _registrar(client)

    primera = _refrescar(client, tokens["refresh_token"])
    segunda = _refrescar(client, tokens["refresh_token"])

    assert primera.status_code == 200
    assert segunda.status_code == 200
    # y los dos sirven de verdad, no son un 200 de adorno
    assert _refrescar(client, primera.json()["refresh_token"]).status_code == 200
    assert _refrescar(client, segunda.json()["refresh_token"]).status_code == 200


def test_reutilizar_un_token_rotado_revoca_toda_la_familia(client, monkeypatch):
    # sin margen de gracia: cualquier repetición cuenta como copia
    monkeypatch.setattr(refresh_token_service, "GRACIA_REUTILIZACION", timedelta(0))
    inicial = _registrar(client)

    vigente = _refrescar(client, inicial["refresh_token"]).json()
    # alguien replica el token viejo: señal de copia, cae la sesión entera
    assert _refrescar(client, inicial["refresh_token"]).status_code == 401

    # y el que estaba en curso, aunque nunca se haya usado, deja de valer
    assert _refrescar(client, vigente["refresh_token"]).status_code == 401


# -------------------------------------------------------------------- logout


def test_tras_logout_el_refresh_token_deja_de_servir(client):
    tokens = _registrar(client)

    salida = client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert salida.status_code == 204

    assert _refrescar(client, tokens["refresh_token"]).status_code == 401


def test_logout_con_un_token_desconocido_no_delata_nada(client):
    # mismo 204 que un logout bueno: si no, el endpoint sirve para averiguar
    # qué tokens existen
    tokens = _registrar(client)
    client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})

    repetido = client.post(
        "/auth/logout", json={"refresh_token": tokens["refresh_token"]}
    )
    assert repetido.status_code == 204
    assert client.post("/auth/logout", json={"refresh_token": "ni-es-un-jwt"}).status_code == 204


# ------------------------------------------------------- sesiones anteriores


def test_un_refresh_token_sin_jti_es_rechazado(client):
    """Los tokens emitidos antes de esto no llevan jti ni fila en la base.

    Se rechazan a propósito: aceptarlos mantendría el agujero abierto durante
    el año que duran. Son dos usuarios de prueba, así que el coste es volver a
    escribir la contraseña una vez.
    """
    datos = _registrar(client)
    antiguo = jwt.decode(datos["refresh_token"], settings.secret_key, algorithms=[settings.algorithm])
    antiguo.pop("jti", None)
    sin_jti = jwt.encode(antiguo, settings.secret_key, algorithm=settings.algorithm)

    assert _refrescar(client, sin_jti).status_code == 401


def test_un_jti_inventado_no_cuela(client):
    _registrar(client)
    falso = jwt.encode(
        {
            "sub": "00000000-0000-0000-0000-000000000001",
            "type": "refresh",
            "jti": "11111111-1111-1111-1111-111111111111",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
        },
        settings.secret_key,
        algorithm=settings.algorithm,
    )

    assert _refrescar(client, falso).status_code == 401
