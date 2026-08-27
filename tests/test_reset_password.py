"""Tests del script de restablecer contraseña (scripts/reset_password.py)."""

from scripts.reset_password import listar_cuentas, restablecer
from tests.conftest import register_and_login


def test_restablecer_permite_entrar_con_la_contrasena_nueva(client, db_session):
    # Arrange
    register_and_login(client, "ana@example.com", "Ana")

    # Act
    codigo = restablecer(db_session, "ana@example.com", "contrasenanueva1")

    # Assert
    assert codigo == 0
    respuesta = client.post(
        "/auth/login",
        data={"username": "ana@example.com", "password": "contrasenanueva1"},
    )
    assert respuesta.status_code == 200


def test_la_contrasena_vieja_deja_de_valer(client, db_session):
    # Arrange
    register_and_login(client, "ana@example.com", "Ana")

    # Act
    restablecer(db_session, "ana@example.com", "contrasenanueva1")

    # Assert
    respuesta = client.post(
        "/auth/login", data={"username": "ana@example.com", "password": "password123"}
    )
    assert respuesta.status_code == 401


def test_email_desconocido_devuelve_error(client, db_session):
    assert restablecer(db_session, "nadie@example.com", "contrasenanueva1") == 1


def test_contrasena_corta_devuelve_error_y_no_toca_la_cuenta(client, db_session):
    # Arrange
    register_and_login(client, "ana@example.com", "Ana")

    # Act
    codigo = restablecer(db_session, "ana@example.com", "corta")

    # Assert
    assert codigo == 1
    respuesta = client.post(
        "/auth/login", data={"username": "ana@example.com", "password": "password123"}
    )
    assert respuesta.status_code == 200


def test_listar_cuentas_muestra_los_emails(client, db_session, capsys):
    # Arrange
    register_and_login(client, "ana@example.com", "Ana")

    # Act
    codigo = listar_cuentas(db_session)

    # Assert
    assert codigo == 0
    assert "ana@example.com" in capsys.readouterr().out
