"""La API no se conecta a la base de datos como dueña de las tablas.

El proceso que atiende peticiones usa un rol que solo puede leer y escribir
filas. Las migraciones, que sí necesitan DDL, corren aparte y solo durante el
despliegue. Así el techo de un fallo de inyección o de lógica es corromper
datos, no borrar el esquema entero.

Estas comprobaciones son sobre los ficheros de despliegue, no sobre la
aplicación: la suite corre contra SQLite y no tiene a quién preguntarle por los
permisos de PostgreSQL. La verificación de verdad —intentar un `CREATE TABLE`
con el rol de la API y recibir «permission denied»— la hace
`scripts/db/aplicar-privilegios.sh` contra la base real.
"""

from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parent.parent

DOCKERFILE = RAIZ / "Dockerfile"
COMPOSE = RAIZ / "docker-compose.yml"
PRIVILEGIOS_SQL = RAIZ / "scripts" / "db" / "privilegios.sql"

# Verbos que la aplicación necesita y ninguno más.
DML = ("SELECT", "INSERT", "UPDATE", "DELETE")
# Lo que no puede poder: cambiar el esquema o vaciar tablas de un golpe.
DDL = ("CREATE", "ALTER", "DROP", "TRUNCATE")


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sql():
    """El script en mayúsculas y sin comentarios.

    Lo que se comprueba son las sentencias; los comentarios explican justo lo
    que NO se hace ("GRANT ALL habría añadido...") y darían falsos positivos.
    """
    lineas = PRIVILEGIOS_SQL.read_text(encoding="utf-8").upper().splitlines()
    return "\n".join(linea.split("--")[0] for linea in lineas)


def _url_de(servicio) -> str:
    return servicio["environment"]["DATABASE_URL"]


class TestArranqueDeLaApi:
    def test_el_contenedor_de_la_api_no_migra(self):
        # Si el arranque de la API ejecuta `alembic upgrade head`, la API tiene
        # que conectarse con permisos de DDL para poder arrancar, y entonces
        # los conserva mientras atiende peticiones.
        assert "alembic" not in DOCKERFILE.read_text(encoding="utf-8")

    def test_hay_un_servicio_dedicado_a_migrar(self, compose):
        migrate = compose["services"]["migrate"]

        assert "alembic upgrade head" in " ".join(migrate["command"])

    def test_la_api_espera_a_que_las_migraciones_terminen(self, compose):
        espera = compose["services"]["api"]["depends_on"]["migrate"]

        assert espera["condition"] == "service_completed_successfully"


class TestUsuariosDeLaBaseDeDatos:
    def test_la_api_no_se_conecta_como_la_dueña(self, compose):
        dueña = compose["services"]["db"]["environment"]["POSTGRES_USER"]

        assert f"//{dueña}:" not in _url_de(compose["services"]["api"])

    def test_las_migraciones_se_conectan_como_la_dueña(self, compose):
        dueña = compose["services"]["db"]["environment"]["POSTGRES_USER"]

        assert f"//{dueña}:" in _url_de(compose["services"]["migrate"])


class TestScriptDePrivilegios:
    def test_el_rol_de_la_api_no_es_superusuario(self, sql):
        assert "NOSUPERUSER" in sql

    def test_concede_los_cuatro_verbos_de_datos(self, sql):
        for verbo in DML:
            assert f"GRANT {verbo}" in sql or f", {verbo}" in sql, verbo

    def test_no_concede_ningun_permiso_de_esquema(self, sql):
        for verbo in DDL:
            assert f"GRANT {verbo}" not in sql, verbo

    def test_no_concede_todo_de_golpe(self, sql):
        # GRANT ALL sobre las tablas incluye TRUNCATE y REFERENCES, y sobre el
        # esquema incluye CREATE. Un atajo aquí anula el resto del arreglo.
        assert "GRANT ALL" not in sql
