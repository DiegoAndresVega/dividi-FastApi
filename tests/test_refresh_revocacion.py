"""Rotación y revocación de refresh tokens.

El refresh token dura un año, así que sin revocación uno robado vale un año
aunque el dueño siga usando la app con normalidad. Estos tests cubren cuatro
piezas: que un token gastado no sirva, que reutilizarlo mate la sesión entera
—porque reutilizarlo es la señal de que alguien lo copió—, que el logout lo
invalide en el servidor y no solo en el móvil, y que cambiar la contraseña
cierre todas las sesiones abiertas.
"""

from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings
from app.security import decode_token
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
    # sin exigir procedencia: es el mismo camino tolerante que usa /auth/refresh
    antiguo = decode_token(datos["refresh_token"], exigir_procedencia=False)
    antiguo.pop("jti", None)
    sin_jti = jwt.encode(antiguo, settings.secret_key.get_secret_value(), algorithm=settings.algorithm)

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
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )

    assert _refrescar(client, falso).status_code == 401


# ------------------------------------------------------ cambio de contraseña


NUEVA_CONTRASENA = "otra-clave-nueva-9"


def _cambiar_contrasena(client, access_token: str, actual: str = "password123"):
    return client.post(
        "/me/password",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"current_password": actual, "new_password": NUEVA_CONTRASENA},
    )


def _entrar(client, password: str, email: str = "ana@example.com") -> dict:
    """Inicia sesión otra vez, como haría un segundo aparato."""
    respuesta = client.post("/auth/login", data={"username": email, "password": password})
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def test_cambiar_la_contrasena_cierra_las_sesiones_de_todos_los_dispositivos(client):
    """Se cambia la contraseña porque se sospecha que alguien más entró.

    Si su refresh token siguiera valiendo, el cambio no lo echaría: se renueva
    en cada uso y le daría otro año cada vez.
    """
    # Arrange: la sesión del móvil y la de otro aparato
    movil = _registrar(client)
    otro = _entrar(client, "password123")

    # Act
    assert _cambiar_contrasena(client, movil["access_token"]).status_code == 204

    # Assert
    assert _refrescar(client, movil["refresh_token"]).status_code == 401
    assert _refrescar(client, otro["refresh_token"]).status_code == 401


def test_el_margen_de_gracia_no_resucita_una_sesion_cerrada(client):
    """Un token gastado hace un instante conserva margen para la carrera benigna.

    Ese margen es para dos peticiones del mismo cliente a la vez, no para sacar
    un token nuevo de una sesión que se acaba de cerrar.
    """
    # Arrange: el token del login se gasta en una rotación y queda en el margen
    inicial = _registrar(client)
    vigente = _refrescar(client, inicial["refresh_token"]).json()

    # Act
    assert _cambiar_contrasena(client, vigente["access_token"]).status_code == 204

    # Assert
    assert _refrescar(client, inicial["refresh_token"]).status_code == 401
    assert _refrescar(client, vigente["refresh_token"]).status_code == 401


def test_con_la_contrasena_nueva_se_abre_una_sesion_que_si_sirve(client):
    # control positivo: lo que se revoca son las sesiones de antes, no la cuenta
    tokens = _registrar(client)
    assert _cambiar_contrasena(client, tokens["access_token"]).status_code == 204

    nueva = _entrar(client, NUEVA_CONTRASENA)

    assert _refrescar(client, nueva["refresh_token"]).status_code == 200


def test_un_cambio_rechazado_no_cierra_ninguna_sesion(client):
    tokens = _registrar(client)

    rechazado = _cambiar_contrasena(client, tokens["access_token"], actual="equivocada99")
    assert rechazado.status_code == 400

    assert _refrescar(client, tokens["refresh_token"]).status_code == 200
