"""La documentación interactiva no se publica en producción.

`/docs`, `/redoc` y `/openapi.json` describen todas las rutas, todos los campos
de cada modelo y todos los códigos de error. En desarrollo eso es cómodo; en
producción es un mapa de la superficie de la API servido a cualquiera.
"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import ENTORNO_DESARROLLO, ENTORNO_PRODUCCION, Settings, settings
from app.main import crear_app

RUTAS_DE_DOCUMENTACION = ("/docs", "/redoc", "/openapi.json")


def _construir(**valores):
    base = {
        "database_url": "postgresql+psycopg2://usuario:clave@servidor:5432/base",
        "secret_key": "x" * 32,
    }
    return Settings(_env_file=None, **{**base, **valores})


@pytest.fixture
def en_produccion(monkeypatch):
    monkeypatch.setattr(settings, "environment", ENTORNO_PRODUCCION)
    yield


@pytest.fixture
def en_desarrollo(monkeypatch):
    monkeypatch.setattr(settings, "environment", ENTORNO_DESARROLLO)
    yield


class TestEntorno:
    def test_por_defecto_asume_produccion(self, monkeypatch):
        # Falla cerrado: si nadie define la variable, se comporta como
        # producción. Olvidarla no debe abrir la documentación.
        monkeypatch.delenv("ENVIRONMENT", raising=False)

        assert _construir().environment == ENTORNO_PRODUCCION

    def test_rechaza_un_entorno_desconocido(self):
        with pytest.raises(ValidationError) as error:
            _construir(environment="produccion")

        assert ENTORNO_DESARROLLO in str(error.value)

    def test_reconoce_el_entorno_de_desarrollo(self):
        assert _construir(environment=ENTORNO_DESARROLLO).es_desarrollo is True

    def test_produccion_no_es_desarrollo(self):
        assert _construir(environment=ENTORNO_PRODUCCION).es_desarrollo is False


class TestDocumentacionEnProduccion:
    def test_las_tres_rutas_devuelven_404(self, en_produccion):
        with TestClient(crear_app()) as cliente:
            for ruta in RUTAS_DE_DOCUMENTACION:
                assert cliente.get(ruta).status_code == 404, ruta

    def test_la_api_sigue_funcionando(self, en_produccion):
        # Cerrar la documentación no puede tumbar la API.
        with TestClient(crear_app()) as cliente:
            assert cliente.get("/health").status_code == 200


class TestDocumentacionEnDesarrollo:
    def test_las_tres_rutas_responden(self, en_desarrollo):
        with TestClient(crear_app()) as cliente:
            for ruta in RUTAS_DE_DOCUMENTACION:
                assert cliente.get(ruta).status_code == 200, ruta
