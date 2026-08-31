"""Validación de la configuración al arrancar.

La clave de firma de los JWT no puede tener valor por defecto: si la variable
de entorno faltase, la API arrancaría firmando todos los tokens con una clave
conocida y cualquiera podría fabricar un token válido para cualquier usuario.
"""

import hashlib

import pytest
from pydantic import ValidationError

from app.config import (
    CLAVES_PUBLICADAS,
    LONGITUD_MINIMA_CLAVE,
    Settings,
    cargar_settings,
)

CLAVE_VALIDA = "x" * LONGITUD_MINIMA_CLAVE
URL_VALIDA = "postgresql+psycopg2://usuario:clave@servidor:5432/base"

# Simula una clave que estuvo publicada. No se usa la real: el criterio del
# punto de seguridad pide que esa cadena no aparezca en el repositorio, y aquí
# se comprueba el mecanismo de bloqueo, que es lo que importa.
CLAVE_FILTRADA = "clave-que-simula-estar-publicada-en-github"


@pytest.fixture
def entorno_limpio(monkeypatch):
    """Sin variables de entorno ni fichero .env: el arranque desde cero."""
    for variable in ("SECRET_KEY", "DATABASE_URL"):
        monkeypatch.delenv(variable, raising=False)
    yield


@pytest.fixture
def clave_filtrada_bloqueada(monkeypatch):
    huella = hashlib.sha256(CLAVE_FILTRADA.encode("utf-8")).hexdigest()
    monkeypatch.setattr("app.config.CLAVES_PUBLICADAS", frozenset({huella}))
    yield


def _construir(**valores):
    # _env_file=None ignora el .env del repositorio: estos tests comprueban el
    # comportamiento con lo que llega por entorno, no con la config local.
    return Settings(_env_file=None, **valores)


class TestSecretKey:
    def test_falta_la_clave(self, entorno_limpio):
        with pytest.raises(ValidationError) as error:
            _construir(database_url=URL_VALIDA)

        assert "secret_key" in str(error.value).lower()

    def test_rechaza_una_clave_publicada(self, entorno_limpio, clave_filtrada_bloqueada):
        with pytest.raises(ValidationError) as error:
            _construir(database_url=URL_VALIDA, secret_key=CLAVE_FILTRADA)

        assert "ejemplo" in str(error.value).lower()

    def test_la_lista_de_claves_publicadas_no_esta_vacia(self):
        # Si alguien la vacía por error, el bloqueo deja de existir en silencio.
        assert CLAVES_PUBLICADAS

    def test_rechaza_una_clave_corta(self, entorno_limpio):
        corta = "x" * (LONGITUD_MINIMA_CLAVE - 1)

        with pytest.raises(ValidationError) as error:
            _construir(database_url=URL_VALIDA, secret_key=corta)

        assert str(LONGITUD_MINIMA_CLAVE) in str(error.value)

    def test_rechaza_una_clave_en_blanco(self, entorno_limpio):
        with pytest.raises(ValidationError):
            _construir(database_url=URL_VALIDA, secret_key="   ")

    def test_acepta_una_clave_valida(self, entorno_limpio):
        settings = _construir(database_url=URL_VALIDA, secret_key=CLAVE_VALIDA)

        assert settings.secret_key == CLAVE_VALIDA

    def test_mide_bytes_y_no_caracteres(self, entorno_limpio):
        # 20 eñes son 20 caracteres pero 40 bytes en UTF-8. El umbral del punto
        # de seguridad está en bytes de entropía, así que debe aceptarse.
        assert _construir(database_url=URL_VALIDA, secret_key="ñ" * 20)


class TestDatabaseUrl:
    def test_falta_la_url(self, entorno_limpio):
        with pytest.raises(ValidationError) as error:
            _construir(secret_key=CLAVE_VALIDA)

        assert "database_url" in str(error.value).lower()


class TestArranque:
    def test_aborta_con_un_mensaje_claro(
        self, entorno_limpio, clave_filtrada_bloqueada, monkeypatch
    ):
        monkeypatch.setenv("SECRET_KEY", CLAVE_FILTRADA)
        monkeypatch.setenv("DATABASE_URL", URL_VALIDA)

        with pytest.raises(SystemExit) as salida:
            cargar_settings(env_file=None)

        mensaje = str(salida.value)
        assert "SECRET_KEY" in mensaje
        assert "ejemplo" in mensaje.lower()
        # Un mensaje útil dice qué hacer, no solo qué falla.
        assert ".env" in mensaje

    def test_aborta_diciendo_que_variable_falta(self, entorno_limpio):
        with pytest.raises(SystemExit) as salida:
            cargar_settings(env_file=None)

        mensaje = str(salida.value)
        assert "SECRET_KEY" in mensaje
        assert "DATABASE_URL" in mensaje
        assert "obligatoria" in mensaje

    def test_no_aborta_con_configuracion_valida(self, entorno_limpio, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", CLAVE_VALIDA)
        monkeypatch.setenv("DATABASE_URL", URL_VALIDA)

        assert cargar_settings(env_file=None).secret_key == CLAVE_VALIDA
