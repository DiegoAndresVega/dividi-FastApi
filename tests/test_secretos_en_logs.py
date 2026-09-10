"""Que ningún secreto ni dato personal acabe en los logs.

El objeto Settings viaja por dentro de la aplicación entera. Basta con que
alguien lo formatee —un traceback, un `print` de depuración, un log de
arranque— para que la clave de firma de los JWT y la contraseña de la base de
datos queden escritas en el registro del contenedor.
"""

import logging

import pytest

from app.config import LONGITUD_MINIMA_CLAVE, Settings, settings

CLAVE = "clave-de-firma-que-no-debe-verse-nunca-jamas"
CONTRASENA_BD = "contrasena-de-la-base-de-datos"
URL = f"postgresql+psycopg2://usuario:{CONTRASENA_BD}@servidor:5432/base"

assert len(CLAVE.encode()) >= LONGITUD_MINIMA_CLAVE


@pytest.fixture
def config():
    return Settings(_env_file=None, database_url=URL, secret_key=CLAVE)


class TestSettingsNoSeChiva:
    def test_el_repr_no_lleva_la_clave_de_firma(self, config):
        assert CLAVE not in repr(config)

    def test_el_str_no_lleva_la_clave_de_firma(self, config):
        assert CLAVE not in str(config)

    def test_el_repr_no_lleva_la_contrasena_de_la_base_de_datos(self, config):
        assert CONTRASENA_BD not in repr(config)

    def test_volcar_el_modelo_no_lleva_los_secretos(self, config):
        volcado = str(config.model_dump())
        assert CLAVE not in volcado
        assert CONTRASENA_BD not in volcado

    def test_los_secretos_siguen_siendo_legibles_a_proposito(self, config):
        # Enmascarar no puede romper el uso normal: firmar y conectar necesitan
        # el valor de verdad, y pedirlo tiene que ser un gesto explícito.
        assert config.secret_key.get_secret_value() == CLAVE
        assert config.database_url.get_secret_value() == URL

    def test_un_error_de_validacion_no_escupe_el_valor(self):
        from pydantic import ValidationError

        from app.config import _describir

        with pytest.raises(ValidationError) as error:
            Settings(_env_file=None, database_url=URL, secret_key="corta")

        assert "corta" not in _describir(error.value)


class TestErrorEnLogin:
    """El criterio de aceptación del punto 5."""

    def test_un_fallo_dentro_del_login_no_imprime_la_contrasena_ni_la_clave(
        self, client, monkeypatch, caplog, capsys
    ):
        # Arrange: un usuario de verdad, para llegar hasta el punto que revienta
        client.post(
            "/auth/register",
            json={
                "email": "alguien@example.com",
                "password": "hunter2-secreta",
                "name": "Alguien",
            },
        )

        def revienta(*args, **kwargs):
            raise RuntimeError("fallo inesperado a mitad del login")

        monkeypatch.setattr("app.routers.auth.verify_password", revienta)

        # Act
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(RuntimeError):
                client.post(
                    "/auth/login",
                    data={
                        "username": "alguien@example.com",
                        "password": "hunter2-secreta",
                    },
                )

        # Assert: ni en los logs ni en lo que sale por stdout/stderr
        salida = caplog.text + capsys.readouterr().out + capsys.readouterr().err
        assert "hunter2-secreta" not in salida
        assert settings.secret_key.get_secret_value() not in salida


class TestFiltroDeLogs:
    def test_enmascara_la_cabecera_authorization(self):
        from app.logging_config import FiltroDeSecretos

        registro = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="peticion con Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.cuerpo.firma",
            args=(),
            exc_info=None,
        )

        FiltroDeSecretos().filter(registro)

        assert "eyJhbGciOiJIUzI1NiJ9.cuerpo.firma" not in registro.getMessage()
        assert "Authorization" in registro.getMessage()

    def test_enmascara_el_codigo_de_invitacion_de_la_ruta(self):
        from app.logging_config import FiltroDeSecretos

        registro = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg='GET /invitations/A1B2C3D4E5F6/check HTTP/1.1" 200',
            args=(),
            exc_info=None,
        )

        FiltroDeSecretos().filter(registro)

        assert "A1B2C3D4E5F6" not in registro.getMessage()

    def test_no_estropea_una_linea_normal(self):
        from app.logging_config import FiltroDeSecretos

        registro = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg='POST /groups/12/expenses HTTP/1.1" 201',
            args=(),
            exc_info=None,
        )

        FiltroDeSecretos().filter(registro)

        assert registro.getMessage() == 'POST /groups/12/expenses HTTP/1.1" 201'


class TestCableado:
    """El filtro puede estar bien y no estar puesto. Esto comprueba lo segundo."""

    def test_una_linea_de_acceso_de_uvicorn_sale_enmascarada(self, caplog):
        from app.logging_config import configurar_logging

        configurar_logging()
        acceso = logging.getLogger("uvicorn.access")

        with caplog.at_level(logging.INFO, logger="uvicorn.access"):
            acceso.info('GET /invitations/CODIGO-SECRETO/check HTTP/1.1" 200')

        assert "CODIGO-SECRETO" not in caplog.text
        assert "/invitations/" in caplog.text

    def test_lo_que_sube_desde_cualquier_libreria_queda_filtrado(self):
        """El caso que de verdad importa: una traza de un tercero.

        Se comprueba contra un manejador real y no con `caplog`, porque el
        manejador es donde acaba escrita la línea: un filtro puesto solo en el
        logger raíz no ve lo que llega propagado desde un hijo.
        """
        import io

        from app.logging_config import configurar_logging

        escrito = io.StringIO()
        manejador = logging.StreamHandler(escrito)
        raiz = logging.getLogger()
        raiz.addHandler(manejador)
        nivel_previo = raiz.level
        raiz.setLevel(logging.INFO)
        try:
            configurar_logging()
            logging.getLogger("libreria.de.terceros").info(
                "fallo al conectar con postgresql://dividi:clave-de-la-bd@db:5432/dividi"
            )
        finally:
            raiz.removeHandler(manejador)
            raiz.setLevel(nivel_previo)

        salida = escrito.getvalue()
        assert "clave-de-la-bd" not in salida
        assert "postgresql://dividi:" in salida
