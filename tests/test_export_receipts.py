"""Tests de exportación CSV (M9) y foto del tique (M8)."""

import pytest

from app.config import settings
from tests.conftest import make_standard_group, register_and_login

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture(autouse=True)
def _receipts_en_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "receipts_dir", str(tmp_path / "receipts"))


def _grupo_con_gasto(client, headers):
    group, owner, _, _ = make_standard_group(client, headers)
    response = client.post(
        f"/groups/{group['id']}/expenses",
        json={
            "description": "Compra semanal",
            "amount": "100",
            "paid_by": owner["id"],
            "split_method": "percentage",
            "category": "comida",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return group, response.json()


# ------------------------------------------------------------------ M9 CSV


def test_export_csv_contains_everything(client):
    headers = register_and_login(client, "ana@example.com")
    group, _ = _grupo_con_gasto(client, headers)

    response = client.get(f"/groups/{group['id']}/export", headers=headers)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    texto = response.text
    for esperado in ["GASTOS", "Compra semanal", "BALANCES", "SALDAR CUENTAS", "100,00"]:
        assert esperado in texto, esperado
    # columnas por miembro con su parte (50/30/20)
    assert "50,00" in texto and "30,00" in texto and "20,00" in texto


def test_export_requires_membership(client):
    ana = register_and_login(client, "ana@example.com")
    bea = register_and_login(client, "bea@example.com")
    group, _ = _grupo_con_gasto(client, ana)

    assert client.get(f"/groups/{group['id']}/export", headers=bea).status_code == 403


# ---------------------------------------------------------------- M8 tique


def test_upload_and_download_receipt(client):
    headers = register_and_login(client, "ana@example.com")
    group, gasto = _grupo_con_gasto(client, headers)

    subida = client.post(
        f"/groups/{group['id']}/expenses/{gasto['id']}/receipt",
        files={"file": ("tique.png", PNG_BYTES, "image/png")},
        headers=headers,
    )

    assert subida.status_code == 200, subida.text
    url = subida.json()["receipt_image_url"]
    assert url == f"/groups/{group['id']}/expenses/{gasto['id']}/receipt"

    descarga = client.get(url, headers=headers)
    assert descarga.status_code == 200
    assert descarga.content == PNG_BYTES
    assert descarga.headers["content-type"].startswith("image/png")


def test_receipt_rejects_non_images(client):
    headers = register_and_login(client, "ana@example.com")
    group, gasto = _grupo_con_gasto(client, headers)

    response = client.post(
        f"/groups/{group['id']}/expenses/{gasto['id']}/receipt",
        files={"file": ("nota.txt", b"hola", "text/plain")},
        headers=headers,
    )

    assert response.status_code == 415


def test_receipt_missing_returns_404(client):
    headers = register_and_login(client, "ana@example.com")
    group, gasto = _grupo_con_gasto(client, headers)

    response = client.get(
        f"/groups/{group['id']}/expenses/{gasto['id']}/receipt", headers=headers
    )

    assert response.status_code == 404


def test_delete_receipt(client):
    headers = register_and_login(client, "ana@example.com")
    group, gasto = _grupo_con_gasto(client, headers)
    client.post(
        f"/groups/{group['id']}/expenses/{gasto['id']}/receipt",
        files={"file": ("tique.png", PNG_BYTES, "image/png")},
        headers=headers,
    )

    borrado = client.delete(
        f"/groups/{group['id']}/expenses/{gasto['id']}/receipt", headers=headers
    )
    assert borrado.status_code == 204

    assert (
        client.get(
            f"/groups/{group['id']}/expenses/{gasto['id']}/receipt", headers=headers
        ).status_code
        == 404
    )


def test_only_creator_or_admin_uploads(client):
    """Un member no puede adjuntar tique a un gasto ajeno."""
    ana = register_and_login(client, "ana@example.com")
    group, gasto = _grupo_con_gasto(client, ana)

    # Bea se registra y se une al grupo con su cuenta (email vinculado)
    bea = register_and_login(client, "bea@example.com", name="Bea")
    respuesta = client.post(
        f"/groups/{group['id']}/members",
        json={
            "email": "bea@example.com",
            "default_percentage": "0",
            "rebalance": {},
        },
        headers=ana,
    )
    assert respuesta.status_code == 201, respuesta.text

    response = client.post(
        f"/groups/{group['id']}/expenses/{gasto['id']}/receipt",
        files={"file": ("tique.png", PNG_BYTES, "image/png")},
        headers=bea,
    )
    assert response.status_code == 403
