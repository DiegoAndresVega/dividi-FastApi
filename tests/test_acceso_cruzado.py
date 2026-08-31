"""Acceso cruzado: nadie ve ni toca lo que no es suyo.

Es el núcleo del producto. Un fallo aquí expone datos financieros de otras
personas, que es el peor escenario de esta aplicación, así que cada router que
devuelve datos de usuario tiene aquí su test: el usuario A pide por id un
recurso del usuario B y debe recibir 403 o 404, nunca los datos.

Se aceptan ambos códigos a propósito. Lo que se comprueba es la propiedad de
seguridad -no hay acceso-, no la elección entre «no existe» y «no puedes»,
que es una decisión de diseño de cada endpoint.
"""

import io

from tests.conftest import create_group, make_standard_group, register_and_login

SIN_ACCESO = (403, 404)


def assert_sin_acceso(respuesta, que: str):
    assert respuesta.status_code in SIN_ACCESO, (
        f"{que}: se esperaba 403 o 404 y llegó {respuesta.status_code} — {respuesta.text}"
    )


def assert_no_filtra(respuesta, secreto: str, que: str):
    """Ni siquiera en el cuerpo del error debe aparecer el dato ajeno."""
    assert secreto not in respuesta.text, f"{que}: el dato ajeno aparece en la respuesta"


def dos_usuarios(client):
    ana = register_and_login(client, "ana@example.com", "Ana")
    beto = register_and_login(client, "beto@example.com", "Beto")
    return ana, beto


# --------------------------------------------------------------- router: me


class TestPerfil:
    def test_cada_uno_ve_solo_su_perfil(self, client):
        ana, beto = dos_usuarios(client)

        assert client.get("/me", headers=ana).json()["email"] == "ana@example.com"
        assert client.get("/me", headers=beto).json()["email"] == "beto@example.com"

    def test_cambiar_la_contrasena_no_afecta_a_otro(self, client):
        ana, beto = dos_usuarios(client)

        client.post(
            "/me/password",
            json={"current_password": "password123", "new_password": "otraclave456"},
            headers=ana,
        )

        # Beto sigue entrando con la suya.
        respuesta = client.post(
            "/auth/login",
            data={"username": "beto@example.com", "password": "password123"},
        )
        assert respuesta.status_code == 200


# --------------------------------------------------- router: personal (/me)


class TestGastosPersonales:
    def _crear(self, client, headers):
        respuesta = client.post(
            "/me/expenses",
            json={"description": "Psicólogo", "amount": "60", "category": "otros"},
            headers=headers,
        )
        assert respuesta.status_code == 201, respuesta.text
        return respuesta.json()

    def test_no_aparecen_en_el_listado_ajeno(self, client):
        ana, beto = dos_usuarios(client)
        gasto = self._crear(client, ana)

        listado = client.get("/me/expenses", headers=beto)
        assert_no_filtra(listado, gasto["id"], "listado de gastos personales")

    def test_no_se_pueden_modificar(self, client):
        ana, beto = dos_usuarios(client)
        gasto = self._crear(client, ana)

        assert_sin_acceso(
            client.patch(
                f"/me/expenses/{gasto['id']}", json={"amount": "1"}, headers=beto
            ),
            "PATCH de un gasto personal ajeno",
        )

    def test_no_se_pueden_borrar(self, client):
        ana, beto = dos_usuarios(client)
        gasto = self._crear(client, ana)

        assert_sin_acceso(
            client.delete(f"/me/expenses/{gasto['id']}", headers=beto),
            "DELETE de un gasto personal ajeno",
        )
        # Y sigue existiendo para su dueña.
        assert client.get("/me/expenses", headers=ana).json()[0]["id"] == gasto["id"]

    def test_las_finanzas_son_privadas(self, client):
        ana, beto = dos_usuarios(client)
        client.put("/me/finances", json={"monthly_income": "3200"}, headers=ana)

        finanzas = client.get("/me/finances", headers=beto).json()
        assert finanzas.get("monthly_income") != "3200"

    def test_el_resumen_no_mezcla_usuarios(self, client):
        ana, beto = dos_usuarios(client)
        self._crear(client, ana)

        resumen = client.get("/me/summary", headers=beto).json()
        assert resumen["personal_total"] in ("0", "0.00", 0)


# ---------------------------------------------------------- router: savings


class TestPlanesDeAhorro:
    def _crear(self, client, headers):
        respuesta = client.post(
            "/savings-plans",
            json={"name": "Japón", "target_amount": "2400", "monthly_amount": "300"},
            headers=headers,
        )
        assert respuesta.status_code == 201, respuesta.text
        return respuesta.json()

    def test_no_se_puede_leer_el_plan_ajeno(self, client):
        ana, beto = dos_usuarios(client)
        plan = self._crear(client, ana)

        respuesta = client.get(f"/savings-plans/{plan['id']}", headers=beto)
        assert_sin_acceso(respuesta, "GET de un plan ajeno")
        assert_no_filtra(respuesta, "Japón", "GET de un plan ajeno")

    def test_no_se_puede_modificar_ni_borrar(self, client):
        ana, beto = dos_usuarios(client)
        plan = self._crear(client, ana)

        assert_sin_acceso(
            client.patch(
                f"/savings-plans/{plan['id']}", json={"name": "Robado"}, headers=beto
            ),
            "PATCH de un plan ajeno",
        )
        assert_sin_acceso(
            client.delete(f"/savings-plans/{plan['id']}", headers=beto),
            "DELETE de un plan ajeno",
        )

    def test_no_se_pueden_anadir_aportaciones(self, client):
        ana, beto = dos_usuarios(client)
        plan = self._crear(client, ana)

        assert_sin_acceso(
            client.post(
                f"/savings-plans/{plan['id']}/entries",
                json={"kind": "monthly", "amount": "300"},
                headers=beto,
            ),
            "POST de aportación a un plan ajeno",
        )


# ---------------------------------------------------- router: notifications


class TestNotificaciones:
    def _notificacion_para_beto(self, client, ana, beto):
        client.post("/friends/requests", json={"email": "beto@example.com"}, headers=ana)
        pendientes = client.get("/notifications", headers=beto).json()
        assert pendientes, "la solicitud de amistad debería notificar a Beto"
        return pendientes[0]

    def test_no_se_ven_las_notificaciones_ajenas(self, client):
        ana, beto = dos_usuarios(client)
        notificacion = self._notificacion_para_beto(client, ana, beto)

        listado = client.get("/notifications", headers=ana)
        assert_no_filtra(listado, notificacion["id"], "listado de notificaciones")

    def test_no_se_puede_marcar_leida_la_ajena(self, client):
        ana, beto = dos_usuarios(client)
        notificacion = self._notificacion_para_beto(client, ana, beto)

        assert_sin_acceso(
            client.post(f"/notifications/{notificacion['id']}/read", headers=ana),
            "marcar leída una notificación ajena",
        )
        # Sigue sin leer para su dueño.
        assert client.get("/notifications/unread-count", headers=beto).json()["unread"] >= 1


# ---------------------------------------------------------- router: friends


class TestAmistades:
    def test_un_tercero_no_puede_aceptar_una_solicitud(self, client):
        ana, beto = dos_usuarios(client)
        carla = register_and_login(client, "carla@example.com", "Carla")
        client.post("/friends/requests", json={"email": "beto@example.com"}, headers=ana)
        solicitud = client.get("/friends/requests", headers=beto).json()[0]

        assert_sin_acceso(
            client.post(f"/friends/requests/{solicitud['id']}/accept", headers=carla),
            "aceptar una solicitud ajena",
        )

    def test_un_tercero_no_puede_cancelar_una_solicitud(self, client):
        ana, beto = dos_usuarios(client)
        carla = register_and_login(client, "carla@example.com", "Carla")
        client.post("/friends/requests", json={"email": "beto@example.com"}, headers=ana)
        solicitud = client.get("/friends/requests", headers=beto).json()[0]

        assert_sin_acceso(
            client.delete(f"/friends/requests/{solicitud['id']}", headers=carla),
            "cancelar una solicitud ajena",
        )

    def test_un_tercero_no_puede_deshacer_una_amistad(self, client):
        ana, beto = dos_usuarios(client)
        carla = register_and_login(client, "carla@example.com", "Carla")
        client.post("/friends/requests", json={"email": "beto@example.com"}, headers=ana)
        solicitud = client.get("/friends/requests", headers=beto).json()[0]
        client.post(f"/friends/requests/{solicitud['id']}/accept", headers=beto)
        amistad = client.get("/friends", headers=ana).json()[0]

        assert_sin_acceso(
            client.delete(f"/friends/{amistad['friendship_id']}", headers=carla),
            "deshacer una amistad ajena",
        )
        assert client.get("/friends", headers=ana).json(), "la amistad debe seguir viva"


# ----------------------------------------------------------- router: groups


class TestGrupos:
    def test_un_extrano_no_ve_el_grupo(self, client):
        ana, beto = dos_usuarios(client)
        grupo = create_group(client, ana, name="Piso de Ana")

        respuesta = client.get(f"/groups/{grupo['id']}", headers=beto)
        assert_sin_acceso(respuesta, "GET de un grupo ajeno")
        assert_no_filtra(respuesta, "Piso de Ana", "GET de un grupo ajeno")

    def test_un_extrano_no_ve_los_balances(self, client):
        ana, beto = dos_usuarios(client)
        grupo = create_group(client, ana)

        assert_sin_acceso(
            client.get(f"/groups/{grupo['id']}/balances", headers=beto),
            "GET de balances ajenos",
        )

    def test_un_extrano_no_ve_la_liquidacion(self, client):
        ana, beto = dos_usuarios(client)
        grupo = create_group(client, ana)

        assert_sin_acceso(
            client.get(f"/groups/{grupo['id']}/settle-up", headers=beto),
            "GET de settle-up ajeno",
        )

    def test_un_extrano_no_puede_anadir_miembros(self, client):
        ana, beto = dos_usuarios(client)
        grupo = create_group(client, ana)

        assert_sin_acceso(
            client.post(
                f"/groups/{grupo['id']}/members",
                json={"display_name": "Intruso", "default_percentage": "0"},
                headers=beto,
            ),
            "añadir miembro a un grupo ajeno",
        )

    def test_un_extrano_no_puede_borrar_el_grupo(self, client):
        ana, beto = dos_usuarios(client)
        grupo = create_group(client, ana)

        assert_sin_acceso(
            client.delete(f"/groups/{grupo['id']}", headers=beto),
            "borrar un grupo ajeno",
        )
        assert client.get(f"/groups/{grupo['id']}", headers=ana).status_code == 200

    def test_el_listado_solo_trae_los_propios(self, client):
        ana, beto = dos_usuarios(client)
        grupo = create_group(client, ana, name="Piso de Ana")

        listado = client.get("/groups", headers=beto)
        assert_no_filtra(listado, grupo["id"], "listado de grupos")


# --------------------------------------------------------- router: expenses


class TestGastosDeGrupo:
    def _grupo_con_gasto(self, client, headers):
        grupo, owner, _, _ = make_standard_group(client, headers)
        respuesta = client.post(
            f"/groups/{grupo['id']}/expenses",
            json={
                "description": "Cena secreta",
                "amount": "80",
                "paid_by": owner["id"],
                "split_method": "equal",
            },
            headers=headers,
        )
        assert respuesta.status_code == 201, respuesta.text
        return grupo, respuesta.json()

    def test_un_extrano_no_lista_los_gastos(self, client):
        ana, beto = dos_usuarios(client)
        grupo, gasto = self._grupo_con_gasto(client, ana)

        respuesta = client.get(f"/groups/{grupo['id']}/expenses", headers=beto)
        assert_sin_acceso(respuesta, "listar gastos de un grupo ajeno")
        assert_no_filtra(respuesta, "Cena secreta", "listar gastos de un grupo ajeno")

    def test_un_extrano_no_lee_un_gasto_por_id(self, client):
        ana, beto = dos_usuarios(client)
        grupo, gasto = self._grupo_con_gasto(client, ana)

        respuesta = client.get(
            f"/groups/{grupo['id']}/expenses/{gasto['id']}", headers=beto
        )
        assert_sin_acceso(respuesta, "GET de un gasto ajeno")
        assert_no_filtra(respuesta, "Cena secreta", "GET de un gasto ajeno")

    def test_un_extrano_no_modifica_ni_borra(self, client):
        ana, beto = dos_usuarios(client)
        grupo, gasto = self._grupo_con_gasto(client, ana)

        assert_sin_acceso(
            client.patch(
                f"/groups/{grupo['id']}/expenses/{gasto['id']}",
                json={"amount": "1"},
                headers=beto,
            ),
            "PATCH de un gasto ajeno",
        )
        assert_sin_acceso(
            client.delete(
                f"/groups/{grupo['id']}/expenses/{gasto['id']}", headers=beto
            ),
            "DELETE de un gasto ajeno",
        )

    def test_no_se_alcanza_un_gasto_ajeno_desde_el_grupo_propio(self, client):
        """El caso sutil: Beto es miembro de SU grupo y mete ahí el id de un
        gasto del grupo de Ana. La ruta es legítima, el recurso no."""
        ana, beto = dos_usuarios(client)
        _, gasto_de_ana = self._grupo_con_gasto(client, ana)
        grupo_de_beto = create_group(client, beto, name="Grupo de Beto")

        respuesta = client.get(
            f"/groups/{grupo_de_beto['id']}/expenses/{gasto_de_ana['id']}", headers=beto
        )
        assert_sin_acceso(respuesta, "gasto de otro grupo por una ruta propia")
        assert_no_filtra(
            respuesta, "Cena secreta", "gasto de otro grupo por una ruta propia"
        )


# -------------------------------------------------------- router: recurring


class TestGastosRecurrentes:
    def _grupo_con_regla(self, client, headers):
        grupo, owner, _, _ = make_standard_group(client, headers)
        respuesta = client.post(
            f"/groups/{grupo['id']}/recurring",
            json={
                "description": "Alquiler secreto",
                "amount": "900",
                "category": "alojamiento",
                "paid_by": owner["id"],
                "split_method": "percentage",
                "day_of_month": 1,
            },
            headers=headers,
        )
        assert respuesta.status_code == 201, respuesta.text
        return grupo, respuesta.json()

    def test_un_extrano_no_lista_las_reglas(self, client):
        ana, beto = dos_usuarios(client)
        grupo, regla = self._grupo_con_regla(client, ana)

        respuesta = client.get(f"/groups/{grupo['id']}/recurring", headers=beto)
        assert_sin_acceso(respuesta, "listar reglas de un grupo ajeno")
        assert_no_filtra(respuesta, "Alquiler secreto", "listar reglas ajenas")

    def test_un_extrano_no_modifica_ni_borra_una_regla(self, client):
        ana, beto = dos_usuarios(client)
        grupo, regla = self._grupo_con_regla(client, ana)

        assert_sin_acceso(
            client.patch(
                f"/groups/{grupo['id']}/recurring/{regla['id']}",
                json={"amount": "1"},
                headers=beto,
            ),
            "PATCH de una regla ajena",
        )
        assert_sin_acceso(
            client.delete(
                f"/groups/{grupo['id']}/recurring/{regla['id']}", headers=beto
            ),
            "DELETE de una regla ajena",
        )

    def test_no_se_alcanza_una_regla_ajena_desde_el_grupo_propio(self, client):
        ana, beto = dos_usuarios(client)
        _, regla_de_ana = self._grupo_con_regla(client, ana)
        grupo_de_beto, _, _, _ = make_standard_group(client, beto)

        assert_sin_acceso(
            client.delete(
                f"/groups/{grupo_de_beto['id']}/recurring/{regla_de_ana['id']}",
                headers=beto,
            ),
            "regla de otro grupo por una ruta propia",
        )


# --------------------------------------------------------- router: payments


class TestPagos:
    def _grupo_con_pago(self, client, headers):
        grupo, owner, bea, _ = make_standard_group(client, headers)
        respuesta = client.post(
            f"/groups/{grupo['id']}/payments",
            json={
                "from_member_id": bea["id"],
                "to_member_id": owner["id"],
                "amount": "25.50",
                "note": "Bizum privado",
            },
            headers=headers,
        )
        assert respuesta.status_code == 201, respuesta.text
        return grupo, respuesta.json()

    def test_un_extrano_no_lista_los_pagos(self, client):
        ana, beto = dos_usuarios(client)
        grupo, pago = self._grupo_con_pago(client, ana)

        respuesta = client.get(f"/groups/{grupo['id']}/payments", headers=beto)
        assert_sin_acceso(respuesta, "listar pagos de un grupo ajeno")
        assert_no_filtra(respuesta, "Bizum privado", "listar pagos ajenos")

    def test_un_extrano_no_deshace_un_pago(self, client):
        ana, beto = dos_usuarios(client)
        grupo, pago = self._grupo_con_pago(client, ana)

        assert_sin_acceso(
            client.delete(
                f"/groups/{grupo['id']}/payments/{pago['id']}", headers=beto
            ),
            "DELETE de un pago ajeno",
        )

    def test_no_se_alcanza_un_pago_ajeno_desde_el_grupo_propio(self, client):
        ana, beto = dos_usuarios(client)
        _, pago_de_ana = self._grupo_con_pago(client, ana)
        grupo_de_beto, _, _, _ = make_standard_group(client, beto)

        assert_sin_acceso(
            client.delete(
                f"/groups/{grupo_de_beto['id']}/payments/{pago_de_ana['id']}",
                headers=beto,
            ),
            "pago de otro grupo por una ruta propia",
        )


# --------------------------------------------------------- router: receipts


class TestTiques:
    def _gasto_con_tique(self, client, headers):
        grupo, owner, _, _ = make_standard_group(client, headers)
        gasto = client.post(
            f"/groups/{grupo['id']}/expenses",
            json={
                "description": "Compra",
                "amount": "30",
                "paid_by": owner["id"],
                "split_method": "equal",
            },
            headers=headers,
        ).json()
        # PNG mínimo válido.
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d494844520000000100000001080600000"
            "01f15c4890000000a49444154789c636000000200010005fe02fea7f6"
            "0d5d0000000049454e44ae426082"
        )
        subida = client.post(
            f"/groups/{grupo['id']}/expenses/{gasto['id']}/receipt",
            files={"file": ("tique.png", io.BytesIO(png), "image/png")},
            headers=headers,
        )
        assert subida.status_code == 200, subida.text
        return grupo, gasto

    def test_un_extrano_no_descarga_el_tique(self, client):
        ana, beto = dos_usuarios(client)
        grupo, gasto = self._gasto_con_tique(client, ana)

        assert_sin_acceso(
            client.get(
                f"/groups/{grupo['id']}/expenses/{gasto['id']}/receipt", headers=beto
            ),
            "descargar un tique ajeno",
        )

    def test_un_extrano_no_borra_el_tique(self, client):
        ana, beto = dos_usuarios(client)
        grupo, gasto = self._gasto_con_tique(client, ana)

        assert_sin_acceso(
            client.delete(
                f"/groups/{grupo['id']}/expenses/{gasto['id']}/receipt", headers=beto
            ),
            "borrar un tique ajeno",
        )
        assert (
            client.get(
                f"/groups/{grupo['id']}/expenses/{gasto['id']}/receipt", headers=ana
            ).status_code
            == 200
        )


# ----------------------------------------------------------- router: export


class TestExportacion:
    def test_un_extrano_no_exporta_el_grupo(self, client):
        ana, beto = dos_usuarios(client)
        grupo, owner, _, _ = make_standard_group(client, ana)
        client.post(
            f"/groups/{grupo['id']}/expenses",
            json={
                "description": "Cena secreta",
                "amount": "80",
                "paid_by": owner["id"],
                "split_method": "equal",
            },
            headers=ana,
        )

        respuesta = client.get(f"/groups/{grupo['id']}/export", headers=beto)
        assert_sin_acceso(respuesta, "exportar un grupo ajeno")
        assert_no_filtra(respuesta, "Cena secreta", "exportar un grupo ajeno")


# ------------------------------------------------------ router: invitations


class TestInvitaciones:
    def _crear(self, client, headers):
        respuesta = client.post(
            "/invitations", json={"email": "invitado@example.com"}, headers=headers
        )
        assert respuesta.status_code == 201, respuesta.text
        return respuesta.json()

    def test_no_se_ven_las_invitaciones_ajenas(self, client):
        ana, beto = dos_usuarios(client)
        invitacion = self._crear(client, ana)

        listado = client.get("/invitations", headers=beto)
        assert_no_filtra(listado, invitacion["id"], "listado de invitaciones")

    def test_no_se_puede_revocar_la_invitacion_ajena(self, client):
        ana, beto = dos_usuarios(client)
        invitacion = self._crear(client, ana)

        assert_sin_acceso(
            client.delete(f"/invitations/{invitacion['id']}", headers=beto),
            "revocar una invitación ajena",
        )
        assert client.get("/invitations", headers=ana).json(), "debe seguir viva"
