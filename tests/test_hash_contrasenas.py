"""Detalles del hash de contraseñas.

bcrypt solo usa los primeros 72 bytes de una contraseña. Según la versión de la
librería, lo que sobra se descarta sin avisar o se lanza una excepción. La API
no puede depender de cuál de las dos toque: el límite se comprueba antes, y se
cuenta en bytes, no en caracteres.
"""

import pytest

from app.config import settings
from app.security import LONGITUD_MAXIMA_CONTRASENA, hash_password, verify_password
from scripts.reset_password import restablecer
from tests.conftest import register_and_login

EMAIL = "ana@example.com"

# 72 bytes justos: el máximo que cabe.
CONTRASENA_72_BYTES = "a" * LONGITUD_MAXIMA_CONTRASENA
# Los mismos 72 bytes y uno más.
CONTRASENA_73_BYTES = CONTRASENA_72_BYTES + "b"
# 37 eñes: 37 caracteres pero 74 bytes en UTF-8. Un límite contado en
# caracteres la deja pasar.
CONTRASENA_74_BYTES_EN_37_CARACTERES = "ñ" * 37


def _registrar(client, password: str):
    return client.post(
        "/auth/register", json={"email": EMAIL, "password": password, "name": "Ana"}
    )


def _entrar(client, password: str):
    return client.post("/auth/login", data={"username": EMAIL, "password": password})


class TestHash:
    def test_dos_contrasenas_con_los_mismos_72_bytes_no_se_validan_entre_si(self):
        # Arrange
        guardado = hash_password(CONTRASENA_72_BYTES)

        # Act
        coincide = verify_password(CONTRASENA_73_BYTES, guardado)

        # Assert
        assert coincide is False

    def test_una_contrasena_de_72_bytes_justos_se_valida(self):
        guardado = hash_password(CONTRASENA_72_BYTES)

        assert verify_password(CONTRASENA_72_BYTES, guardado) is True

    def test_no_se_hashea_una_contrasena_de_mas_de_72_bytes(self):
        with pytest.raises(ValueError):
            hash_password(CONTRASENA_74_BYTES_EN_37_CARACTERES)

    def test_el_coste_sale_de_la_configuracion(self, monkeypatch):
        # Arrange
        monkeypatch.setattr(settings, "bcrypt_rounds", 10)

        # Act
        guardado = hash_password("password123")

        # Assert
        assert guardado.startswith("$2b$10$")

    def test_cambiar_el_coste_no_invalida_los_hashes_anteriores(self, monkeypatch):
        # Arrange: el coste va escrito dentro de cada hash, así que subirlo
        # solo afecta a las contraseñas que se guarden a partir de entonces
        monkeypatch.setattr(settings, "bcrypt_rounds", 10)
        guardado = hash_password("password123")

        # Act
        monkeypatch.setattr(settings, "bcrypt_rounds", 12)

        # Assert
        assert verify_password("password123", guardado) is True


class TestRegistro:
    def test_rechaza_mas_de_72_bytes_aunque_sean_menos_de_72_caracteres(self, client):
        respuesta = _registrar(client, CONTRASENA_74_BYTES_EN_37_CARACTERES)

        assert respuesta.status_code == 422
        # la app enseña `msg` tal cual: tiene que leerse sin prefijos técnicos
        assert respuesta.json()["detail"][0]["msg"].startswith("La contraseña es demasiado larga")

    def test_acepta_72_bytes_justos_y_se_puede_entrar(self, client):
        assert _registrar(client, CONTRASENA_72_BYTES).status_code == 201

        assert _entrar(client, CONTRASENA_72_BYTES).status_code == 200


class TestLogin:
    def test_mas_de_72_bytes_con_el_mismo_prefijo_no_entra(self, client):
        # Arrange
        _registrar(client, CONTRASENA_72_BYTES)

        # Act
        respuesta = _entrar(client, CONTRASENA_73_BYTES)

        # Assert
        assert respuesta.status_code == 401


class TestCambioDeContrasena:
    def test_rechaza_una_nueva_de_mas_de_72_bytes(self, client):
        # Arrange
        headers = register_and_login(client, EMAIL)

        # Act
        respuesta = client.post(
            "/me/password",
            headers=headers,
            json={
                "current_password": "password123",
                "new_password": CONTRASENA_74_BYTES_EN_37_CARACTERES,
            },
        )

        # Assert
        assert respuesta.status_code == 422

    def test_una_actual_de_mas_de_72_bytes_es_incorrecta(self, client):
        # Arrange
        headers = register_and_login(client, EMAIL)

        # Act
        respuesta = client.post(
            "/me/password",
            headers=headers,
            json={"current_password": "x" * 100, "new_password": "nueva-clave-9"},
        )

        # Assert
        assert respuesta.status_code == 400


class TestScriptDeRestablecer:
    def test_rechaza_mas_de_72_bytes_y_no_toca_la_cuenta(self, client, db_session):
        # Arrange
        register_and_login(client, EMAIL)

        # Act
        codigo = restablecer(db_session, EMAIL, CONTRASENA_74_BYTES_EN_37_CARACTERES)

        # Assert
        assert codigo == 1
        assert _entrar(client, "password123").status_code == 200
