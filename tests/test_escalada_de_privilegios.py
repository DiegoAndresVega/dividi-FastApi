"""Escalada de privilegios dentro de un grupo.

La batería de acceso cruzado (punto 15) ya comprueba que quien no es miembro
de un grupo no ve nada. Esto es el escalón siguiente: quien **sí** es miembro,
pero con rol `member`, no puede hacer lo que solo debe poder un `admin`.

`require_admin()` existía y se usaba, pero no había ni un test que lo
demostrase. Una comprobación de autorización sin test es una comprobación que
alguien borra en un refactor sin que salte nada.

Cada caso lleva su **control positivo**: se comprueba que el admin SÍ puede
hacer lo mismo. Sin eso, un 403 que viniera de cualquier otro sitio —una ruta
mal escrita, un id inexistente— daría el test por bueno por el motivo
equivocado.
"""

import pytest

from tests.conftest import create_group, imagen_de_prueba, register_and_login

CATEGORIA = "alojamiento"


@pytest.fixture
def grupo_con_socio(client):
    """Ana (admin) y Bea (member), las dos con cuenta real, en el mismo grupo."""
    ana = register_and_login(client, "ana@example.com", "Ana")
    bea = register_and_login(client, "bea@example.com", "Bea")
    grupo = create_group(client, ana)
    duena = grupo["members"][0]

    respuesta = client.post(
        f"/groups/{grupo['id']}/members",
        json={
            "email": "bea@example.com",
            "default_percentage": "50",
            "rebalance": {duena["id"]: "50"},
        },
        headers=ana,
    )
    assert respuesta.status_code == 201, respuesta.text
    socia = respuesta.json()

    # El montaje tiene que ser el que creemos: si Bea saliera admin, todos los
    # tests de abajo pasarían sin comprobar nada.
    assert socia["role"] == "member"
    return {"ana": ana, "bea": bea, "grupo": grupo, "duena": duena, "socia": socia}


def _crear_gasto(client, headers, grupo_id, paid_by, descripcion="Cena"):
    respuesta = client.post(
        f"/groups/{grupo_id}/expenses",
        json={
            "description": descripcion,
            "amount": "30",
            "paid_by": paid_by,
            "split_method": "equal",
        },
        headers=headers,
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


class TestOperacionesDeAdministracion:
    """Un `member` no puede administrar el grupo."""

    def test_no_puede_editar_el_grupo(self, client, grupo_con_socio):
        g = grupo_con_socio
        ruta = f"/groups/{g['grupo']['id']}"
        cuerpo = {"name": "Renombrado"}

        assert client.patch(ruta, json=cuerpo, headers=g["bea"]).status_code == 403
        # control positivo: el admin sí
        assert client.patch(ruta, json=cuerpo, headers=g["ana"]).status_code == 200

    def test_no_puede_anadir_miembros(self, client, grupo_con_socio):
        g = grupo_con_socio
        ruta = f"/groups/{g['grupo']['id']}/members"
        cuerpo = {
            "display_name": "Carlos",
            "default_percentage": "20",
            "rebalance": {g["duena"]["id"]: "40", g["socia"]["id"]: "40"},
        }

        assert client.post(ruta, json=cuerpo, headers=g["bea"]).status_code == 403
        assert client.post(ruta, json=cuerpo, headers=g["ana"]).status_code == 201

    def test_no_puede_ascenderse_a_si_misma(self, client, grupo_con_socio):
        """El caso que más importa: subirse el rol es la escalada entera."""
        g = grupo_con_socio
        ruta = f"/groups/{g['grupo']['id']}/members/{g['socia']['id']}"

        assert (
            client.patch(ruta, json={"role": "admin"}, headers=g["bea"]).status_code == 403
        )

        # y sigue siendo member después del intento
        grupo = client.get(f"/groups/{g['grupo']['id']}", headers=g["bea"]).json()
        socia = next(m for m in grupo["members"] if m["id"] == g["socia"]["id"])
        assert socia["role"] == "member"

    def test_no_puede_degradar_al_admin(self, client, grupo_con_socio):
        g = grupo_con_socio
        ruta = f"/groups/{g['grupo']['id']}/members/{g['duena']['id']}"

        assert (
            client.patch(ruta, json={"role": "member"}, headers=g["bea"]).status_code == 403
        )

    def test_no_puede_cambiar_los_porcentajes(self, client, grupo_con_socio):
        g = grupo_con_socio
        ruta = f"/groups/{g['grupo']['id']}/members/{g['socia']['id']}"
        cuerpo = {
            "default_percentage": "10",
            "rebalance": {g["duena"]["id"]: "90"},
        }

        assert client.patch(ruta, json=cuerpo, headers=g["bea"]).status_code == 403
        assert client.patch(ruta, json=cuerpo, headers=g["ana"]).status_code == 200

    def test_no_puede_expulsar_a_nadie(self, client, grupo_con_socio):
        g = grupo_con_socio
        ruta = f"/groups/{g['grupo']['id']}/members/{g['duena']['id']}"

        assert client.delete(ruta, headers=g["bea"]).status_code == 403

    def test_no_puede_expulsarse_para_llevarse_el_grupo(self, client, grupo_con_socio):
        """Expulsar al admin dejaría el grupo sin dueño y con Bea dentro."""
        g = grupo_con_socio
        antes = client.get(f"/groups/{g['grupo']['id']}", headers=g["bea"]).json()

        client.delete(
            f"/groups/{g['grupo']['id']}/members/{g['duena']['id']}", headers=g["bea"]
        )

        despues = client.get(f"/groups/{g['grupo']['id']}", headers=g["bea"]).json()
        assert len(despues["members"]) == len(antes["members"])

    def test_no_puede_borrar_el_grupo(self, client, grupo_con_socio):
        g = grupo_con_socio
        ruta = f"/groups/{g['grupo']['id']}"

        assert client.delete(ruta, headers=g["bea"]).status_code == 403
        assert client.delete(ruta, headers=g["ana"]).status_code == 204


class TestRecursosAjenosDentroDelGrupo:
    """Un `member` solo toca lo suyo; el admin, todo."""

    def test_no_puede_editar_un_gasto_ajeno(self, client, grupo_con_socio):
        g = grupo_con_socio
        gasto = _crear_gasto(client, g["ana"], g["grupo"]["id"], g["duena"]["id"])
        ruta = f"/groups/{g['grupo']['id']}/expenses/{gasto['id']}"

        assert (
            client.patch(ruta, json={"description": "Otra"}, headers=g["bea"]).status_code
            == 403
        )
        assert (
            client.patch(ruta, json={"description": "Otra"}, headers=g["ana"]).status_code
            == 200
        )

    def test_no_puede_borrar_un_gasto_ajeno(self, client, grupo_con_socio):
        g = grupo_con_socio
        gasto = _crear_gasto(client, g["ana"], g["grupo"]["id"], g["duena"]["id"])
        ruta = f"/groups/{g['grupo']['id']}/expenses/{gasto['id']}"

        assert client.delete(ruta, headers=g["bea"]).status_code == 403
        assert client.delete(ruta, headers=g["ana"]).status_code == 204

    def test_si_puede_con_los_suyos(self, client, grupo_con_socio):
        """La otra mitad: la restricción no puede dejarla sin poder trabajar."""
        g = grupo_con_socio
        gasto = _crear_gasto(
            client, g["bea"], g["grupo"]["id"], g["socia"]["id"], "Suyo"
        )
        ruta = f"/groups/{g['grupo']['id']}/expenses/{gasto['id']}"

        assert (
            client.patch(ruta, json={"description": "Cambiado"}, headers=g["bea"]).status_code
            == 200
        )
        assert client.delete(ruta, headers=g["bea"]).status_code == 204

    def test_no_puede_tocar_una_regla_recurrente_ajena(self, client, grupo_con_socio):
        g = grupo_con_socio
        regla = client.post(
            f"/groups/{g['grupo']['id']}/recurring",
            json={
                "description": "Alquiler",
                "amount": "900",
                "category": CATEGORIA,
                "paid_by": g["duena"]["id"],
                "split_method": "equal",
                "day_of_month": 1,
            },
            headers=g["ana"],
        ).json()
        ruta = f"/groups/{g['grupo']['id']}/recurring/{regla['id']}"

        assert (
            client.patch(ruta, json={"active": False}, headers=g["bea"]).status_code == 403
        )
        assert client.delete(ruta, headers=g["bea"]).status_code == 403
        assert client.delete(ruta, headers=g["ana"]).status_code == 204

    def test_no_puede_tocar_el_tique_de_un_gasto_ajeno(self, client, grupo_con_socio):
        g = grupo_con_socio
        gasto = _crear_gasto(client, g["ana"], g["grupo"]["id"], g["duena"]["id"])
        ruta = f"/groups/{g['grupo']['id']}/expenses/{gasto['id']}/receipt"
        fichero = {"file": ("t.png", imagen_de_prueba(), "image/png")}

        assert client.post(ruta, files=fichero, headers=g["bea"]).status_code == 403
        assert client.delete(ruta, headers=g["bea"]).status_code == 403
