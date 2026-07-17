from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app

# Por defecto los tests corren con registro abierto; los tests de invitaciones
# reactivan require_invite puntualmente con monkeypatch.
settings.require_invite = False
# El rate limiting se desactiva por defecto en los tests (los de seguridad lo
# reactivan puntualmente). Debe fijarse ANTES de importar la app.
settings.rate_limit_enabled = False

# SQLite en memoria para tests: rápido y sin dependencias externas.
# StaticPool + check_same_thread=False para compartir la misma conexión
# entre el TestClient y las fixtures.
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def as_decimal(value) -> Decimal:
    """Normaliza un valor numérico de la respuesta JSON a Decimal."""
    return Decimal(str(value))


def register_and_login(client, email: str, name: str = "Test User") -> dict:
    """Registra un usuario, hace login y devuelve los headers de autorización."""
    response = client.post(
        "/auth/register",
        json={"email": email, "password": "password123", "name": name},
    )
    assert response.status_code == 201, response.text
    response = client.post(
        "/auth/login", data={"username": email, "password": "password123"}
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_group(client, headers, name: str = "Viaje", currency: str = "EUR") -> dict:
    response = client.post(
        "/groups", json={"name": name, "default_currency": currency}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_member(client, headers, group_id, display_name, percentage, rebalance) -> dict:
    """Añade un invitado sin cuenta rebalanceando porcentajes existentes."""
    response = client.post(
        f"/groups/{group_id}/members",
        json={
            "display_name": display_name,
            "default_percentage": str(percentage),
            "rebalance": {k: str(v) for k, v in rebalance.items()},
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def make_standard_group(client, headers):
    """Grupo con 3 miembros: owner (50%), Bea (30%), Carlos (20%)."""
    group = create_group(client, headers)
    owner_member = group["members"][0]
    bea = add_member(
        client, headers, group["id"], "Bea", 30, {owner_member["id"]: 70}
    )
    carlos = add_member(
        client,
        headers,
        group["id"],
        "Carlos",
        20,
        {owner_member["id"]: 50, bea["id"]: 30},
    )
    return group, owner_member, bea, carlos
