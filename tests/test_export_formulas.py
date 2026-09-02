"""Ninguna celda del CSV exportado se abre como fórmula.

El export vuelca texto que escriben los usuarios: descripción del gasto,
categoría, nombre del miembro y nombre del grupo. Excel y LibreOffice tratan
como fórmula toda celda que empiece por `=`, `+`, `-` o `@`, así que un miembro
del grupo podría escribir una descripción que se ejecute en el ordenador de
otro cuando este abra el fichero descargado.

Los importes negativos son la excepción: `-12,50` empieza por `-` pero una hoja
de cálculo lo lee como número, y ponerle el apóstrofo delante convertiría en
texto todos los balances en contra. Se escapa lo que no sea un número.
"""

import csv
import io

import pytest

from tests.conftest import make_standard_group, register_and_login

# Con estos caracteres una hoja de cálculo empieza a interpretar la celda.
INICIOS_DE_FORMULA = ("=", "+", "-", "@", "\t", "\r")

FORMULAS = (
    "=1+1",
    "@SUM(A1)",
    "+1+1",
    "-2+3",
    "=cmd|'/c calc'!A1",
)


def _celdas(csv_texto: str) -> list[str]:
    sin_bom = csv_texto.lstrip("﻿")
    lector = csv.reader(io.StringIO(sin_bom), delimiter=";")
    return [celda for fila in lector for celda in fila]


def _es_numero(celda: str) -> bool:
    return celda.lstrip("-").replace(",", "", 1).isdigit()


def _celdas_peligrosas(csv_texto: str) -> list[str]:
    return [
        celda
        for celda in _celdas(csv_texto)
        if celda.startswith(INICIOS_DE_FORMULA) and not _es_numero(celda)
    ]


def _exportar(client, headers, group_id: str) -> str:
    respuesta = client.get(f"/groups/{group_id}/export", headers=headers)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.text


def _crear_gasto(client, headers, group_id, pagador_id, **campos):
    cuerpo = {
        "description": "Compra semanal",
        "amount": "100",
        "paid_by": pagador_id,
        "split_method": "percentage",
        "category": "comida",
    }
    respuesta = client.post(
        f"/groups/{group_id}/expenses", json={**cuerpo, **campos}, headers=headers
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


class TestTextoDeLosUsuarios:
    @pytest.mark.parametrize("formula", FORMULAS)
    def test_la_descripcion_de_un_gasto_sale_neutralizada(self, client, formula):
        headers = register_and_login(client, "ana@example.com")
        grupo, owner, _, _ = make_standard_group(client, headers)
        _crear_gasto(client, headers, grupo["id"], owner["id"], description=formula)

        csv_texto = _exportar(client, headers, grupo["id"])

        assert f"'{formula}" in csv_texto
        assert _celdas_peligrosas(csv_texto) == []

    def test_la_categoria_tambien(self, client):
        headers = register_and_login(client, "ana@example.com")
        grupo, owner, _, _ = make_standard_group(client, headers)
        _crear_gasto(client, headers, grupo["id"], owner["id"], category="=1+1")

        assert _celdas_peligrosas(_exportar(client, headers, grupo["id"])) == []

    def test_el_nombre_del_grupo_tambien(self, client):
        headers = register_and_login(client, "ana@example.com")
        respuesta = client.post(
            "/groups",
            json={"name": "=1+1", "default_currency": "EUR"},
            headers=headers,
        )
        assert respuesta.status_code == 201, respuesta.text

        assert _celdas_peligrosas(_exportar(client, headers, respuesta.json()["id"])) == []

    def test_el_nombre_de_un_miembro_tambien(self, client):
        # El nombre del miembro sale dos veces: en la cabecera de GASTOS y en
        # la sección de BALANCES. Las dos pasan por el mismo sitio.
        headers = register_and_login(client, "ana@example.com")
        grupo = client.post(
            "/groups", json={"name": "Viaje", "default_currency": "EUR"},
            headers=headers,
        ).json()
        respuesta = client.post(
            f"/groups/{grupo['id']}/members",
            json={
                "display_name": "@SUM(A1)",
                "default_percentage": "30",
                "rebalance": {grupo["members"][0]["id"]: "70"},
            },
            headers=headers,
        )
        assert respuesta.status_code == 201, respuesta.text

        csv_texto = _exportar(client, headers, grupo["id"])

        assert csv_texto.count("'@SUM(A1)") == 2
        assert _celdas_peligrosas(csv_texto) == []


class TestLoQueNoSeToca:
    def test_los_importes_negativos_siguen_siendo_numeros(self, client):
        # Quien no ha pagado nada tiene el balance en negativo. Si el arreglo
        # escapase también los números, el CSV dejaría de sumar en Excel.
        headers = register_and_login(client, "ana@example.com")
        grupo, owner, _, _ = make_standard_group(client, headers)
        _crear_gasto(client, headers, grupo["id"], owner["id"])

        celdas = _celdas(_exportar(client, headers, grupo["id"]))
        negativas = [celda for celda in celdas if celda.startswith("-")]

        assert negativas, "el grupo de prueba debería tener balances negativos"
        assert all(_es_numero(celda) for celda in negativas)

    def test_el_texto_normal_no_se_toca(self, client):
        headers = register_and_login(client, "ana@example.com")
        grupo, owner, _, _ = make_standard_group(client, headers)
        _crear_gasto(client, headers, grupo["id"], owner["id"])

        assert "'" not in _exportar(client, headers, grupo["id"])


class TestNombreDelFichero:
    def test_un_nombre_hostil_no_se_escapa_de_la_cabecera(self, client):
        headers = register_and_login(client, "ana@example.com")
        respuesta = client.post(
            "/groups",
            json={"name": 'x"; rm -rf /\r\nX-Malo: 1', "default_currency": "EUR"},
            headers=headers,
        )
        assert respuesta.status_code == 201, respuesta.text

        descarga = client.get(
            f"/groups/{respuesta.json()['id']}/export", headers=headers
        )

        assert descarga.status_code == 200, descarga.text
        cabecera = descarga.headers["content-disposition"]
        assert cabecera.count('"') == 2
        assert "X-Malo" not in descarga.headers

    def test_un_nombre_no_ascii_no_rompe_la_descarga(self, client):
        # Las cabeceras HTTP viajan en latin-1: un nombre en japonés reventaba
        # la respuesta entera al intentar codificarla.
        headers = register_and_login(client, "ana@example.com")
        respuesta = client.post(
            "/groups", json={"name": "日本語", "default_currency": "EUR"},
            headers=headers,
        )
        assert respuesta.status_code == 201, respuesta.text

        descarga = client.get(
            f"/groups/{respuesta.json()['id']}/export", headers=headers
        )

        assert descarga.status_code == 200, descarga.text
