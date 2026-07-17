"""Tests del endurecimiento anti-abuso: rate limiting, tamaño de petición,
cabeceras de seguridad y el tope de recuperación de gastos recurrentes."""

import pytest

from app.config import settings
from app.rate_limit import limiter
from tests.conftest import make_standard_group, register_and_login


# ------------------------------------------------------------- rate limiting


@pytest.fixture
def rate_limit_on():
    """Activa el rate limiting y limpia el contador entre tests."""
    limiter.reset()
    settings.rate_limit_enabled = True
    yield
    settings.rate_limit_enabled = False
    limiter.reset()


def test_login_is_rate_limited(client, rate_limit_on):
    # el límite de auth es 10/minuto: al 11.º intento salta el 429
    codes = [
        client.post(
            "/auth/login", data={"username": "x@example.com", "password": "nope"}
        ).status_code
        for _ in range(11)
    ]

    assert codes.count(401) == 10
    assert codes[-1] == 429


def test_normal_endpoints_not_throttled_at_low_volume(client, rate_limit_on):
    headers = register_and_login(client, "ana@example.com")
    # unas pocas peticiones normales nunca deben toparse con el límite general
    for _ in range(15):
        assert client.get("/groups", headers=headers).status_code == 200


# --------------------------------------------------------- tamaño de petición


def test_oversized_request_is_rejected(client):
    # Content-Length por encima del máximo → 413 sin leer el cuerpo
    huge = settings.max_request_bytes + 1
    response = client.post(
        "/auth/login",
        data={"username": "a@b.com", "password": "x"},
        headers={"content-length": str(huge)},
    )
    assert response.status_code == 413


# --------------------------------------------------------- cabeceras seguridad


def test_security_headers_present(client):
    response = client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "content-security-policy" in response.headers


# ------------------------------------------------ recurrentes: sin backdating


def test_recurring_rejects_past_start_period(client):
    headers = register_and_login(client, "ana@example.com")
    group, owner, _, _ = make_standard_group(client, headers)

    response = client.post(
        f"/groups/{group['id']}/recurring",
        json={
            "description": "Alquiler",
            "amount": "900",
            "paid_by": owner["id"],
            "split_method": "percentage",
            "day_of_month": 1,
            "start_period": "2000-01",
        },
        headers=headers,
    )

    assert response.status_code == 400
    assert "pasado" in response.json()["detail"].lower()
