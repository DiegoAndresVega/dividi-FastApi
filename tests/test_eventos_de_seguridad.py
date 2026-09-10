"""Registro de eventos de seguridad.

Hoy solo existen las líneas de acceso de uvicorn: dicen qué ruta se pidió,
pero no quién. Si mañana pasa algo, hay que poder reconstruir quién hizo qué,
y para eso hace falta que cada operación sensible deje una línea con el id del
usuario y la IP, y ninguna con la contraseña o el token.
"""

import json
import logging

import pytest

from tests.conftest import make_standard_group, register_and_login


@pytest.fixture
def eventos(caplog):
    """Los eventos ya descodificados, en orden."""

    class Recogidos:
        def __init__(self, registro):
            self._registro = registro

        def _lineas(self):
            return [
                json.loads(r.getMessage())
                for r in self._registro.records
                if r.name == "dividi.seguridad"
            ]

        def de(self, nombre):
            return [e for e in self._lineas() if e["evento"] == nombre]

        def todos(self):
            return self._lineas()

    with caplog.at_level(logging.INFO, logger="dividi.seguridad"):
        yield Recogidos(caplog)


class TestAutenticacion:
    def test_un_login_correcto_deja_constancia_con_el_usuario(self, client, eventos):
        # Arrange
        client.post(
            "/auth/register",
            json={"email": "ana@example.com", "password": "password123", "name": "Ana"},
        )

        # Act
        client.post(
            "/auth/login", data={"username": "ana@example.com", "password": "password123"}
        )

        # Assert
        registrados = eventos.de("login_correcto")
        assert len(registrados) == 1
        assert registrados[0]["user_id"]
        assert registrados[0]["ip"]

    def test_un_login_fallido_deja_constancia(self, client, eventos):
        # Arrange
        client.post(
            "/auth/register",
            json={"email": "ana@example.com", "password": "password123", "name": "Ana"},
        )

        # Act
        client.post(
            "/auth/login", data={"username": "ana@example.com", "password": "la-que-no-es"}
        )

        # Assert
        assert len(eventos.de("login_fallido")) == 1

    def test_un_login_fallido_no_deja_escrita_la_contrasena(self, client, eventos):
        client.post(
            "/auth/login", data={"username": "nadie@example.com", "password": "hunter2"}
        )

        assert "hunter2" not in json.dumps(eventos.todos())

    def test_el_alta_deja_constancia(self, client, eventos):
        client.post(
            "/auth/register",
            json={"email": "ana@example.com", "password": "password123", "name": "Ana"},
        )

        assert len(eventos.de("alta_de_usuario")) == 1

    def test_el_refresh_deja_constancia_y_no_escribe_el_token(self, client, eventos):
        # Arrange
        client.post(
            "/auth/register",
            json={"email": "ana@example.com", "password": "password123", "name": "Ana"},
        )
        respuesta = client.post(
            "/auth/login", data={"username": "ana@example.com", "password": "password123"}
        )
        refresh = respuesta.json()["refresh_token"]

        # Act
        client.post("/auth/refresh", json={"refresh_token": refresh})

        # Assert
        assert len(eventos.de("refresh")) == 1
        assert refresh not in json.dumps(eventos.todos())

    def test_reutilizar_un_refresh_token_deja_un_evento_aparte(
        self, client, eventos, monkeypatch
    ):
        # Arrange: sin margen de gracia, la repetición cuenta como robo
        import datetime

        monkeypatch.setattr(
            "app.services.refresh_token_service.GRACIA_REUTILIZACION",
            datetime.timedelta(seconds=0),
        )
        client.post(
            "/auth/register",
            json={"email": "ana@example.com", "password": "password123", "name": "Ana"},
        )
        respuesta = client.post(
            "/auth/login", data={"username": "ana@example.com", "password": "password123"}
        )
        refresh = respuesta.json()["refresh_token"]
        client.post("/auth/refresh", json={"refresh_token": refresh})

        # Act: el mismo token, otra vez
        client.post("/auth/refresh", json={"refresh_token": refresh})

        # Assert
        assert len(eventos.de("refresh_token_reutilizado")) == 1

    def test_el_logout_deja_constancia(self, client, eventos):
        client.post(
            "/auth/register",
            json={"email": "ana@example.com", "password": "password123", "name": "Ana"},
        )
        respuesta = client.post(
            "/auth/login", data={"username": "ana@example.com", "password": "password123"}
        )

        client.post(
            "/auth/logout", json={"refresh_token": respuesta.json()["refresh_token"]}
        )

        assert len(eventos.de("logout")) == 1


class TestCambioDeContrasena:
    def test_deja_constancia_sin_escribir_ninguna_de_las_dos(self, client, eventos):
        # Arrange
        headers = register_and_login(client, "ana@example.com")

        # Act
        client.post(
            "/me/password",
            headers=headers,
            json={"current_password": "password123", "new_password": "otra-distinta-9"},
        )

        # Assert
        assert len(eventos.de("cambio_de_contrasena")) == 1
        volcado = json.dumps(eventos.todos())
        assert "password123" not in volcado
        assert "otra-distinta-9" not in volcado


class TestOperacionesQueCambianAlgo:
    """El criterio: reconstruir quién hizo qué."""

    def test_un_borrado_deja_quien_y_desde_donde(self, client, eventos):
        # Arrange
        headers = register_and_login(client, "ana@example.com")
        grupo = client.post(
            "/groups", headers=headers, json={"name": "Viaje", "currency": "EUR"}
        ).json()

        # Act
        client.delete(f"/groups/{grupo['id']}", headers=headers)

        # Assert
        borrados = [
            e
            for e in eventos.de("operacion")
            if e["metodo"] == "DELETE" and e["estado"] == 204
        ]
        assert len(borrados) == 1
        assert borrados[0]["user_id"]
        assert borrados[0]["ip"]
        assert borrados[0]["ruta"].startswith("/groups/")

    def test_un_cambio_de_rol_deja_constancia(self, client, eventos):
        # Arrange
        headers = register_and_login(client, "ana@example.com")
        grupo, _, miembro, _ = make_standard_group(client, headers)

        # Act
        respuesta = client.patch(
            f"/groups/{grupo['id']}/members/{miembro['id']}",
            headers=headers,
            json={"role": "admin"},
        )

        # Assert
        assert respuesta.status_code == 200, respuesta.text
        cambios = [e for e in eventos.de("operacion") if e["metodo"] == "PATCH"]
        assert any(c["ruta"].endswith(f"/members/{miembro['id']}") for c in cambios)
        assert all(c["user_id"] for c in cambios)

    def test_una_lectura_no_ensucia_el_registro(self, client, eventos):
        headers = register_and_login(client, "ana@example.com")

        client.get("/groups", headers=headers)

        assert eventos.de("operacion") == []

    def test_ninguna_operacion_escribe_la_cabecera_authorization(self, client, eventos):
        headers = register_and_login(client, "ana@example.com")

        client.post("/groups", headers=headers, json={"name": "Viaje", "currency": "EUR"})

        assert headers["Authorization"].removeprefix("Bearer ") not in json.dumps(
            eventos.todos()
        )


class TestFormato:
    def test_cada_evento_es_una_linea_de_json_con_lo_minimo(self, client, eventos):
        client.post(
            "/auth/register",
            json={"email": "ana@example.com", "password": "password123", "name": "Ana"},
        )

        for evento in eventos.todos():
            assert set(evento) >= {"evento", "momento", "ip"}
            assert "\n" not in json.dumps(evento)
