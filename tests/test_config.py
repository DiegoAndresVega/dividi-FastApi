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
    COSTE_BCRYPT_MAXIMO,
    COSTE_BCRYPT_MINIMO,
    LONGITUD_MINIMA_CLAVE,
    Settings,
    cargar_settings,
)

CLAVE_VALIDA = "x" * LONGITUD_MINIMA_CLAVE
URL_VALIDA = "postgresql+psycopg2://usuario:clave@servidor:5432/base"
URL_EN_LOCALHOST = "postgresql+psycopg2://usuario:clave@localhost:5432/base"

# Simula una clave que estuvo publicada. No se usa la real: el criterio del
# punto de seguridad pide que esa cadena no aparezca en el repositorio, y aquí
# se comprueba el mecanismo de bloqueo, que es lo que importa.
CLAVE_FILTRADA = "clave-que-simula-estar-publicada-en-github"


@pytest.fixture
def entorno_limpio(monkeypatch):
    """Sin variables de entorno ni fichero .env: el arranque desde cero."""
    for variable in ("SECRET_KEY", "DATABASE_URL", "BCRYPT_ROUNDS", "ENVIRONMENT"):
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

        assert settings.secret_key.get_secret_value() == CLAVE_VALIDA

    def test_mide_bytes_y_no_caracteres(self, entorno_limpio):
        # 20 eñes son 20 caracteres pero 40 bytes en UTF-8. El umbral del punto
        # de seguridad está en bytes de entropía, así que debe aceptarse.
        assert _construir(database_url=URL_VALIDA, secret_key="ñ" * 20)


class TestDatabaseUrl:
    def test_falta_la_url(self, entorno_limpio):
        with pytest.raises(ValidationError) as error:
            _construir(secret_key=CLAVE_VALIDA)

        assert "database_url" in str(error.value).lower()

    @pytest.mark.parametrize(
        "host", ["localhost", "LOCALHOST", "127.0.0.1", "127.0.1.1", "[::1]", "0.0.0.0"]
    )
    def test_rechaza_localhost_en_produccion(self, entorno_limpio, host):
        # Dentro del contenedor, localhost es el propio contenedor y no la base
        # de datos: la API arrancaría y fallaría en la primera petición.
        url = f"postgresql+psycopg2://usuario:clave@{host}:5432/base"

        with pytest.raises(ValidationError) as error:
            _construir(database_url=url, secret_key=CLAVE_VALIDA, environment="prod")

        assert "localhost" in str(error.value).lower()

    def test_sin_environment_tambien_se_rechaza(self, entorno_limpio):
        # prod es el valor por defecto: olvidar la variable no relaja la regla.
        with pytest.raises(ValidationError):
            _construir(database_url=URL_EN_LOCALHOST, secret_key=CLAVE_VALIDA)

    def test_acepta_localhost_en_desarrollo(self, entorno_limpio):
        settings = _construir(
            database_url=URL_EN_LOCALHOST, secret_key=CLAVE_VALIDA, environment="dev"
        )

        assert settings.es_desarrollo

    def test_acepta_el_nombre_del_servicio_en_produccion(self, entorno_limpio):
        url = "postgresql+psycopg2://usuario:clave@db:5432/base"

        assert _construir(database_url=url, secret_key=CLAVE_VALIDA, environment="prod")

    def test_no_juzga_una_url_sin_host(self, entorno_limpio):
        # SQLite en memoria, la de la suite: no hay host con el que comparar.
        assert _construir(
            database_url="sqlite://", secret_key=CLAVE_VALIDA, environment="prod"
        )

    def test_rechaza_una_url_ilegible(self, entorno_limpio):
        with pytest.raises(ValidationError) as error:
            _construir(database_url="esto no es una url", secret_key=CLAVE_VALIDA)

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

    def test_aborta_si_la_base_de_datos_esta_en_localhost(self, entorno_limpio, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", CLAVE_VALIDA)
        monkeypatch.setenv("DATABASE_URL", URL_EN_LOCALHOST)

        with pytest.raises(SystemExit) as salida:
            cargar_settings(env_file=None)

        mensaje = str(salida.value)
        assert "DATABASE_URL" in mensaje
        assert "localhost" in mensaje
        # Ni la contraseña de la base de datos ni la URL entera en el log.
        assert "usuario:clave" not in mensaje

    def test_aborta_con_una_url_ilegible_sin_traceback_de_sqlalchemy(
        self, entorno_limpio, monkeypatch
    ):
        monkeypatch.setenv("SECRET_KEY", CLAVE_VALIDA)
        monkeypatch.setenv("DATABASE_URL", "esto no es una url")

        with pytest.raises(SystemExit) as salida:
            cargar_settings(env_file=None)

        assert "DATABASE_URL" in str(salida.value)

    def test_no_aborta_con_configuracion_valida(self, entorno_limpio, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", CLAVE_VALIDA)
        monkeypatch.setenv("DATABASE_URL", URL_VALIDA)

        assert cargar_settings(env_file=None).secret_key.get_secret_value() == CLAVE_VALIDA


class TestCosteBcrypt:
    def test_por_defecto_es_12(self, entorno_limpio):
        # El mismo que traía bcrypt: fijarlo no cambia los hashes de hoy, solo
        # impide que los cambie una actualización de la librería.
        settings = _construir(database_url=URL_VALIDA, secret_key=CLAVE_VALIDA)

        assert settings.bcrypt_rounds == 12

    def test_se_lee_del_entorno(self, entorno_limpio, monkeypatch):
        monkeypatch.setenv("BCRYPT_ROUNDS", "13")

        settings = _construir(database_url=URL_VALIDA, secret_key=CLAVE_VALIDA)

        assert settings.bcrypt_rounds == 13

    def test_rechaza_un_coste_por_debajo_del_minimo(self, entorno_limpio):
        with pytest.raises(ValidationError) as error:
            _construir(
                database_url=URL_VALIDA,
                secret_key=CLAVE_VALIDA,
                bcrypt_rounds=COSTE_BCRYPT_MINIMO - 1,
            )

        assert str(COSTE_BCRYPT_MINIMO) in str(error.value)

    def test_rechaza_un_coste_por_encima_del_maximo(self, entorno_limpio):
        with pytest.raises(ValidationError) as error:
            _construir(
                database_url=URL_VALIDA,
                secret_key=CLAVE_VALIDA,
                bcrypt_rounds=COSTE_BCRYPT_MAXIMO + 1,
            )

        assert str(COSTE_BCRYPT_MAXIMO) in str(error.value)

    def test_rechaza_un_coste_que_dejaria_el_login_sin_responder(self, entorno_limpio):
        # Cada punto duplica el tiempo: con 15 un hash pasa de 1 s, y con el
        # tope de CPU del contenedor unos pocos logins a la vez lo acaparan.
        with pytest.raises(ValidationError):
            _construir(database_url=URL_VALIDA, secret_key=CLAVE_VALIDA, bcrypt_rounds=15)
