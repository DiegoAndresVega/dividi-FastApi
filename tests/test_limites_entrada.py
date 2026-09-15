"""Cada campo que entra por la API tiene un rango declarado.

Dos capas:

1. Un **guardián** que recorre todos los esquemas de entrada y falla si alguien
   añade mañana un campo sin tope. Es lo que hace que el criterio siga
   cumpliéndose dentro de un año, y no solo el día que se escribió.
2. Tests de valores límite para los casos donde el tope tiene consecuencias:
   listas que se convierten en filas de la base de datos, fechas imposibles y
   monedas inventadas.
"""

import importlib
import inspect
import pkgutil
import typing
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum

import pytest
from annotated_types import Ge, Gt, Le, Lt
from pydantic import BaseModel, ValidationError

import app.schemas
from app.schemas.limites import (
    ANOS_HACIA_ATRAS,
    MAX_MIEMBROS_POR_GRUPO,
    MAX_PARTES,
    MAX_PRESUPUESTOS,
    MONEDAS_ADMITIDAS,
    RangoDeclarado,
)
from tests.conftest import create_group, make_standard_group, register_and_login

# Tipos que no necesitan tope porque su forma ya lo impone: un UUID mide lo que
# mide, un bool tiene dos valores y un Enum los que declare.
TIPOS_ACOTADOS_POR_SI_MISMOS = (uuid.UUID, bool)

# Un esquema de salida no es entrada de nadie: describe lo que devolvemos.
SUFIJOS_DE_SALIDA = ("Out", "Detail", "Summary", "Check", "Token")


def _modelos_de_entrada() -> list[type[BaseModel]]:
    modelos = []
    for info in pkgutil.iter_modules(app.schemas.__path__):
        modulo = importlib.import_module(f"app.schemas.{info.name}")
        for nombre, objeto in vars(modulo).items():
            es_modelo = inspect.isclass(objeto) and issubclass(objeto, BaseModel)
            if not es_modelo or objeto is BaseModel:
                continue
            if objeto.__module__ != modulo.__name__:
                continue  # importado de otro módulo; se revisa en el suyo
            if nombre.endswith(SUFIJOS_DE_SALIDA):
                continue
            modelos.append(objeto)
    return sorted(set(modelos), key=lambda m: (m.__module__, m.__name__))


def _sin_optional(anotacion):
    """`Optional[X]` -> `X`. Deja el resto como está."""
    if typing.get_origin(anotacion) is typing.Union:
        args = [a for a in typing.get_args(anotacion) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return anotacion


def _tiene(metadatos, atributo: str) -> bool:
    """Si algún metadato declara ese tope.

    Se mira por atributo y no por tipo porque el mismo tope llega de dos
    formas: `Field(max_length=...)` deja un `MaxLen`, y `StringConstraints`
    un único objeto con `max_length` dentro.
    """
    return any(getattr(m, atributo, None) is not None for m in metadatos)


def _falta_tope(campo, anotacion) -> str | None:
    """Devuelve el motivo por el que el campo no está acotado, o None."""
    metadatos = list(campo.metadata)

    # Un rango comprobado por un validador no se puede leer de los metadatos:
    # quien lo escribe deja la marca RangoDeclarado para decir cuál es.
    if any(isinstance(m, RangoDeclarado) for m in metadatos):
        return None

    tipo = _sin_optional(anotacion)
    origen = typing.get_origin(tipo) or tipo

    if origen in TIPOS_ACOTADOS_POR_SI_MISMOS:
        return None
    if inspect.isclass(origen) and issubclass(origen, (Enum, BaseModel)):
        return None

    if origen in (list, dict, set, tuple):
        if not _tiene(metadatos, "max_length"):
            return "es una colección sin max_length"
        return None

    if origen is str:
        if not _tiene(metadatos, "max_length") and not _tiene(metadatos, "pattern"):
            return "es texto sin max_length ni pattern"
        return None

    if origen in (int, float, Decimal):
        tiene_minimo = any(isinstance(m, (Ge, Gt)) for m in metadatos)
        tiene_maximo = any(isinstance(m, (Le, Lt)) for m in metadatos)
        if not (tiene_minimo and tiene_maximo):
            return "es un número sin mínimo y máximo declarados"
        return None

    if origen is datetime:
        return "es una fecha sin rango declarado"

    return None


class TestGuardianDeLimites:
    """Que nadie vuelva a añadir un campo de entrada sin tope."""

    def test_hay_esquemas_de_entrada_que_revisar(self):
        # Si el descubrimiento se rompe, el resto del guardián pasaría en vacío.
        assert len(_modelos_de_entrada()) >= 15

    def test_todos_los_campos_de_entrada_estan_acotados(self):
        sin_tope = []
        for modelo in _modelos_de_entrada():
            for nombre, campo in modelo.model_fields.items():
                motivo = _falta_tope(campo, campo.annotation)
                if motivo:
                    sin_tope.append(
                        f"{modelo.__module__}.{modelo.__name__}.{nombre} {motivo}"
                    )

        assert not sin_tope, "Campos de entrada sin rango declarado:\n" + "\n".join(
            sin_tope
        )


class TestMonedas:
    def test_una_moneda_fuera_de_la_lista_no_entra(self, client):
        headers = register_and_login(client, "moneda@test.com")
        respuesta = client.post(
            "/groups", json={"name": "Viaje", "default_currency": "ZZZ"}, headers=headers
        )
        assert respuesta.status_code == 422

    def test_las_monedas_de_la_lista_entran(self, client):
        headers = register_and_login(client, "monedas-ok@test.com")
        for moneda in ("EUR", "USD", "GBP"):
            assert moneda in MONEDAS_ADMITIDAS
            respuesta = client.post(
                "/groups",
                json={"name": f"Viaje {moneda}", "default_currency": moneda},
                headers=headers,
            )
            assert respuesta.status_code == 201, respuesta.text

    def test_el_codigo_sigue_exigiendo_tres_letras_mayusculas(self, client):
        headers = register_and_login(client, "moneda-formato@test.com")
        respuesta = client.post(
            "/groups", json={"name": "Viaje", "default_currency": "eur"}, headers=headers
        )
        assert respuesta.status_code == 422


class TestFechas:
    def test_un_pago_en_el_ano_9999_no_entra(self, client):
        headers = register_and_login(client, "fecha-futuro@test.com")
        grupo, owner, bea, _ = make_standard_group(client, headers)
        respuesta = client.post(
            f"/groups/{grupo['id']}/payments",
            json={
                "from_member_id": owner["id"],
                "to_member_id": bea["id"],
                "amount": "10.00",
                "paid_at": "9999-12-31T00:00:00Z",
            },
            headers=headers,
        )
        assert respuesta.status_code == 422

    def test_un_pago_de_hace_siglos_no_entra(self, client):
        headers = register_and_login(client, "fecha-pasado@test.com")
        grupo, owner, bea, _ = make_standard_group(client, headers)
        demasiado_atras = datetime.now(timezone.utc) - timedelta(
            days=365 * (ANOS_HACIA_ATRAS + 1)
        )
        respuesta = client.post(
            f"/groups/{grupo['id']}/payments",
            json={
                "from_member_id": owner["id"],
                "to_member_id": bea["id"],
                "amount": "10.00",
                "paid_at": demasiado_atras.isoformat(),
            },
            headers=headers,
        )
        assert respuesta.status_code == 422

    def test_un_pago_de_ayer_si_entra(self, client):
        headers = register_and_login(client, "fecha-ayer@test.com")
        grupo, owner, bea, _ = make_standard_group(client, headers)
        ayer = datetime.now(timezone.utc) - timedelta(days=1)
        respuesta = client.post(
            f"/groups/{grupo['id']}/payments",
            json={
                "from_member_id": owner["id"],
                "to_member_id": bea["id"],
                "amount": "10.00",
                "paid_at": ayer.isoformat(),
            },
            headers=headers,
        )
        assert respuesta.status_code == 201, respuesta.text

    def test_una_fecha_sin_zona_horaria_se_admite(self, client):
        """La app manda fechas locales sin sufijo; no puede romperlas el tope."""
        headers = register_and_login(client, "fecha-naive@test.com")
        respuesta = client.post(
            "/me/expenses",
            json={
                "description": "Café",
                "amount": "1.50",
                "created_at": "2026-01-15T10:30:00",
            },
            headers=headers,
        )
        assert respuesta.status_code == 201, respuesta.text


class TestColecciones:
    def test_un_grupo_con_demasiados_miembros_iniciales_no_entra(self, client):
        headers = register_and_login(client, "muchos-miembros@test.com")
        miembros = [
            {"display_name": f"Invitado {i}", "default_percentage": "0"}
            for i in range(MAX_MIEMBROS_POR_GRUPO + 1)
        ]
        respuesta = client.post(
            "/groups",
            json={"name": "Multitud", "members": miembros},
            headers=headers,
        )
        assert respuesta.status_code == 422

    def test_un_gasto_con_demasiados_splits_no_entra(self, client):
        headers = register_and_login(client, "muchos-splits@test.com")
        grupo, owner, _, _ = make_standard_group(client, headers)
        splits = [
            {"group_member_id": owner["id"], "exact_amount": "0.01"}
            for _ in range(MAX_MIEMBROS_POR_GRUPO + 1)
        ]
        respuesta = client.post(
            f"/groups/{grupo['id']}/expenses",
            json={
                "description": "Cena",
                "amount": "100.00",
                "paid_by": owner["id"],
                "split_method": "exact",
                "splits": splits,
            },
            headers=headers,
        )
        assert respuesta.status_code == 422

    def test_demasiados_presupuestos_no_entran(self, client):
        headers = register_and_login(client, "muchos-budgets@test.com")
        budgets = [
            {"category": f"cat{i}", "limit_amount": "10.00"}
            for i in range(MAX_PRESUPUESTOS + 1)
        ]
        respuesta = client.put(
            "/me/finances", json={"budgets": budgets}, headers=headers
        )
        assert respuesta.status_code == 422

    def test_un_rebalance_enorme_no_entra(self, client):
        headers = register_and_login(client, "rebalance-enorme@test.com")
        grupo = create_group(client, headers)
        rebalance = {
            str(uuid.uuid4()): "0" for _ in range(MAX_MIEMBROS_POR_GRUPO + 1)
        }
        respuesta = client.post(
            f"/groups/{grupo['id']}/members",
            json={"display_name": "Bea", "rebalance": rebalance},
            headers=headers,
        )
        assert respuesta.status_code == 422


class TestNumerosSinTope:
    def test_un_reparto_por_partes_desorbitado_no_entra(self, client):
        headers = register_and_login(client, "partes@test.com")
        grupo, owner, bea, _ = make_standard_group(client, headers)
        respuesta = client.post(
            f"/groups/{grupo['id']}/expenses",
            json={
                "description": "Cena",
                "amount": "100.00",
                "paid_by": owner["id"],
                "split_method": "shares",
                "splits": [
                    {"group_member_id": owner["id"], "shares": MAX_PARTES + 1},
                    {"group_member_id": bea["id"], "shares": 1},
                ],
            },
            headers=headers,
        )
        assert respuesta.status_code == 422

    def test_un_exact_amount_desorbitado_no_entra(self, client):
        headers = register_and_login(client, "exacto@test.com")
        grupo, owner, bea, _ = make_standard_group(client, headers)
        respuesta = client.post(
            f"/groups/{grupo['id']}/expenses",
            json={
                "description": "Cena",
                "amount": "100.00",
                "paid_by": owner["id"],
                "split_method": "exact",
                "splits": [
                    {"group_member_id": owner["id"], "exact_amount": "999999999999999"},
                    {"group_member_id": bea["id"], "exact_amount": "1.00"},
                ],
            },
            headers=headers,
        )
        assert respuesta.status_code == 422


class TestTextoLibre:
    def test_un_nombre_de_grupo_solo_de_espacios_no_entra(self, client):
        headers = register_and_login(client, "espacios@test.com")
        respuesta = client.post(
            "/groups", json={"name": "     "}, headers=headers
        )
        assert respuesta.status_code == 422

    def test_el_nombre_se_guarda_sin_espacios_alrededor(self, client):
        headers = register_and_login(client, "trim@test.com")
        respuesta = client.post(
            "/groups", json={"name": "  Viaje a Roma  "}, headers=headers
        )
        assert respuesta.status_code == 201, respuesta.text
        assert respuesta.json()["name"] == "Viaje a Roma"

    def test_una_contrasena_actual_desorbitada_no_entra(self, client):
        headers = register_and_login(client, "pass-larga@test.com")
        respuesta = client.post(
            "/me/password",
            json={
                "current_password": "x" * 10_000,
                "new_password": "otra-contrasena-valida-123",  # gitleaks:allow
            },
            headers=headers,
        )
        assert respuesta.status_code == 422

    def test_un_refresh_token_desorbitado_no_entra(self, client):
        respuesta = client.post(
            "/auth/refresh", json={"refresh_token": "x" * 10_000}
        )
        assert respuesta.status_code == 422


class TestEsquemasDirectamente:
    """Los bordes exactos, sin pasar por HTTP."""

    def test_el_maximo_de_partes_entra_y_uno_mas_no(self):
        from app.schemas.expense import SplitInput

        SplitInput(group_member_id=uuid.uuid4(), shares=MAX_PARTES)
        with pytest.raises(ValidationError):
            SplitInput(group_member_id=uuid.uuid4(), shares=MAX_PARTES + 1)

    def test_el_maximo_de_miembros_entra_y_uno_mas_no(self):
        from app.schemas.group import GroupCreate, GroupMemberInit

        miembro = GroupMemberInit(display_name="Bea")
        GroupCreate(name="Viaje", members=[miembro] * MAX_MIEMBROS_POR_GRUPO)
        with pytest.raises(ValidationError):
            GroupCreate(name="Viaje", members=[miembro] * (MAX_MIEMBROS_POR_GRUPO + 1))
