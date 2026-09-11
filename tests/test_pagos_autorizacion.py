"""Quién puede deshacer un pago ya registrado (punto 51).

Borrar un pago **des-salda una cuenta**: la deuda vuelve a aparecer y en la
base de datos no queda rastro de que ese pago existió. Hasta ahora bastaba con
ser miembro del grupo, así que un tercero que no tenía nada que ver con el
pago podía deshacerlo.

Regla que se implementa aquí: pueden borrar el pagador, el receptor, quien lo
registró y un `admin`. Cualquier otro miembro recibe 403.

La **creación** se deja abierta a propósito: un invitado sin cuenta
(`GroupMember.user_id` nulo) no puede registrar sus propios pagos, y la
pantalla de saldar de la app sugiere pagos entre terceros. Hay un test que lo
fija para que no se restrinja por descuido.

Cada caso lleva su control positivo: sin él, un 403 venido de otro sitio
—una ruta mal escrita, un id inexistente— daría el test por bueno por el
motivo equivocado.
"""

import uuid

import pytest

from app.models import Payment
from tests.conftest import create_group, register_and_login


def _incorporar(client, headers_admin, grupo, email, porcentajes):
    respuesta = client.post(
        f"/groups/{grupo['id']}/members",
        json={
            "email": email,
            "default_percentage": "25",
            "rebalance": {k: str(v) for k, v in porcentajes.items()},
        },
        headers=headers_admin,
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


@pytest.fixture
def grupo(client):
    """Ana (admin), Bea y Carlos (member), las tres con cuenta real.

    Más Dani, invitada sin cuenta: es el caso que impide restringir la
    creación de pagos a las partes implicadas.
    """
    ana = register_and_login(client, "ana@example.com", "Ana")
    bea = register_and_login(client, "bea@example.com", "Bea")
    carlos = register_and_login(client, "carlos@example.com", "Carlos")

    g = create_group(client, ana)
    m_ana = g["members"][0]
    m_bea = _incorporar(client, ana, g, "bea@example.com", {m_ana["id"]: 75})
    m_carlos = _incorporar(
        client, ana, g, "carlos@example.com", {m_ana["id"]: 50, m_bea["id"]: 25}
    )
    respuesta = client.post(
        f"/groups/{g['id']}/members",
        json={
            "display_name": "Dani",
            "default_percentage": "25",
            "rebalance": {m_ana["id"]: 25, m_bea["id"]: 25, m_carlos["id"]: 25},
        },
        headers=ana,
    )
    assert respuesta.status_code == 201, respuesta.text
    m_dani = respuesta.json()

    # El montaje tiene que ser el que creemos: si Bea o Carlos salieran admin,
    # los 403 de abajo no se producirían nunca.
    assert m_bea["role"] == "member" and m_carlos["role"] == "member"
    return {
        "id": g["id"],
        "ana": ana,
        "bea": bea,
        "carlos": carlos,
        "m_ana": m_ana,
        "m_bea": m_bea,
        "m_carlos": m_carlos,
        "m_dani": m_dani,
    }


def _registrar_pago(client, headers, grupo, origen, destino, importe="20.00"):
    respuesta = client.post(
        f"/groups/{grupo['id']}/payments",
        json={
            "from_member_id": origen["id"],
            "to_member_id": destino["id"],
            "amount": importe,
        },
        headers=headers,
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _borrar(client, headers, grupo, pago):
    return client.delete(
        f"/groups/{grupo['id']}/payments/{pago['id']}", headers=headers
    )


def _ids_de_pagos(client, headers, grupo):
    respuesta = client.get(f"/groups/{grupo['id']}/payments", headers=headers)
    assert respuesta.status_code == 200, respuesta.text
    return [p["id"] for p in respuesta.json()]


class TestBorrado:
    def test_un_tercero_no_implicado_no_puede_borrar(self, client, grupo):
        pago = _registrar_pago(
            client, grupo["ana"], grupo, grupo["m_bea"], grupo["m_ana"]
        )

        respuesta = _borrar(client, grupo["carlos"], grupo, pago)

        assert respuesta.status_code == 403, respuesta.text
        # El 403 no basta: el pago tiene que seguir ahí.
        assert pago["id"] in _ids_de_pagos(client, grupo["carlos"], grupo)

    def test_el_pagador_si_puede_borrar(self, client, grupo):
        pago = _registrar_pago(
            client, grupo["ana"], grupo, grupo["m_bea"], grupo["m_ana"]
        )

        respuesta = _borrar(client, grupo["bea"], grupo, pago)

        assert respuesta.status_code == 204, respuesta.text
        assert pago["id"] not in _ids_de_pagos(client, grupo["ana"], grupo)

    def test_el_receptor_si_puede_borrar(self, client, grupo):
        pago = _registrar_pago(
            client, grupo["ana"], grupo, grupo["m_carlos"], grupo["m_bea"]
        )

        respuesta = _borrar(client, grupo["bea"], grupo, pago)

        assert respuesta.status_code == 204, respuesta.text

    def test_quien_lo_registro_puede_borrarlo_aunque_no_sea_parte(self, client, grupo):
        # Carlos apunta un pago entre Ana y Bea; si se equivoca, tiene que
        # poder deshacer lo suyo sin depender de un admin.
        pago = _registrar_pago(
            client, grupo["carlos"], grupo, grupo["m_bea"], grupo["m_ana"]
        )

        respuesta = _borrar(client, grupo["carlos"], grupo, pago)

        assert respuesta.status_code == 204, respuesta.text

    def test_un_admin_puede_borrar_cualquier_pago(self, client, grupo):
        pago = _registrar_pago(
            client, grupo["bea"], grupo, grupo["m_carlos"], grupo["m_bea"]
        )

        respuesta = _borrar(client, grupo["ana"], grupo, pago)

        assert respuesta.status_code == 204, respuesta.text

    def test_pago_antiguo_sin_autor_sigue_la_misma_regla(self, client, grupo, db_session):
        """Las filas anteriores a la migración tienen `created_by_id` nulo.

        No se rellenan: un nulo significa «no se sabe quién lo apuntó», así que
        mandan los implicados y el admin. Un tercero sigue sin poder.
        """
        pago = _registrar_pago(
            client, grupo["ana"], grupo, grupo["m_bea"], grupo["m_ana"]
        )
        fila = db_session.get(Payment, uuid.UUID(pago["id"]))
        assert fila is not None and fila.created_by_id is not None
        fila.created_by_id = None
        db_session.commit()

        assert _borrar(client, grupo["carlos"], grupo, pago).status_code == 403
        assert _borrar(client, grupo["bea"], grupo, pago).status_code == 204


class TestCreacion:
    def test_cualquier_miembro_puede_registrar_un_pago_entre_otros_dos(
        self, client, grupo
    ):
        """Deliberado: Dani no tiene cuenta y nunca podría apuntar lo suyo."""
        respuesta = client.post(
            f"/groups/{grupo['id']}/payments",
            json={
                "from_member_id": grupo["m_dani"]["id"],
                "to_member_id": grupo["m_ana"]["id"],
                "amount": "15.00",
            },
            headers=grupo["carlos"],
        )

        assert respuesta.status_code == 201, respuesta.text

    def test_el_pago_guarda_quien_lo_registro(self, client, grupo, db_session):
        pago = _registrar_pago(
            client, grupo["carlos"], grupo, grupo["m_dani"], grupo["m_ana"]
        )

        fila = db_session.get(Payment, uuid.UUID(pago["id"]))

        assert fila is not None
        assert fila.created_by_id is not None
