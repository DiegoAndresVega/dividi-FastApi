"""Qué tokens acepta el servidor (punto 10).

`jwt.decode` con la clave y el algoritmo correctos ya rechaza lo obvio, pero
callaba dos cosas: un token al que le falte un claim que el código da por
hecho —`sub`, `type`— pasaba la verificación criptográfica y se descubría más
tarde, y nada distinguía un token emitido por otro entorno que compartiera la
clave.

Ahora los access tokens exigen `iss` y `aud`. Los refresh **no**, a propósito:
los que hay en circulación duran un año y se emitieron sin esos claims;
rechazarlos devolvería a todos los usuarios a la pantalla de login. Un refresh
robado sigue frenado por su `jti`, que se comprueba contra la tabla
`refresh_tokens` de esta base de datos, así que la audiencia añadía poco ahí.
Lo que sí se comprueba: si un refresh trae `iss` o `aud`, tienen que cuadrar.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.config import settings
from app.security import create_access_token, create_refresh_token, decode_token
from tests.conftest import register_and_login

RUTA_PROTEGIDA = "/me"


def _clave() -> str:
    return settings.secret_key.get_secret_value()


def _firmar(claims: dict, clave: str | None = None, algoritmo: str = "HS256") -> str:
    return jwt.encode(claims, clave or _clave(), algorithm=algoritmo)


def _claims_de_access(user_id: str, **cambios) -> dict:
    ahora = datetime.now(timezone.utc)
    base = {
        "sub": user_id,
        "type": "access",
        "iat": ahora,
        "exp": ahora + timedelta(minutes=30),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    base.update(cambios)
    return {k: v for k, v in base.items() if v is not None}


@pytest.fixture
def usuario(client):
    headers = register_and_login(client, "ana@example.com", "Ana")
    user_id = client.get(RUTA_PROTEGIDA, headers=headers).json()["id"]
    # El refresh del login, no uno firmado a mano: solo los emitidos por la API
    # están anotados en `refresh_tokens`, y sin esa fila /auth/refresh los
    # rechaza por otro motivo distinto del que se quiere probar.
    respuesta = client.post(
        "/auth/login", data={"username": "ana@example.com", "password": "password123"}
    )
    assert respuesta.status_code == 200, respuesta.text
    return {"headers": headers, "id": user_id, "refresh": respuesta.json()["refresh_token"]}


def _con(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestAccessToken:
    def test_un_token_normal_entra(self, client, usuario):
        """Control positivo: sin esto, cualquier 401 daría los tests por buenos."""
        token = create_access_token(usuario["id"])
        assert client.get(RUTA_PROTEGIDA, headers=_con(token)).status_code == 200

    def test_firmado_con_otra_clave_devuelve_401(self, client, usuario):
        token = _firmar(
            _claims_de_access(usuario["id"]), clave="otra-clave-distinta-de-32-bytes-si"
        )
        assert client.get(RUTA_PROTEGIDA, headers=_con(token)).status_code == 401

    def test_caducado_devuelve_401(self, client, usuario):
        ayer = datetime.now(timezone.utc) - timedelta(days=1)
        token = _firmar(
            _claims_de_access(usuario["id"], iat=ayer, exp=ayer + timedelta(minutes=30))
        )
        assert client.get(RUTA_PROTEGIDA, headers=_con(token)).status_code == 401

    def test_sin_type_devuelve_401(self, client, usuario):
        token = _firmar(_claims_de_access(usuario["id"], type=None))
        assert client.get(RUTA_PROTEGIDA, headers=_con(token)).status_code == 401

    def test_sin_sub_devuelve_401(self, client, usuario):
        token = _firmar(_claims_de_access(usuario["id"], sub=None))
        assert client.get(RUTA_PROTEGIDA, headers=_con(token)).status_code == 401

    def test_sin_exp_devuelve_401(self, client, usuario):
        token = _firmar(_claims_de_access(usuario["id"], exp=None))
        assert client.get(RUTA_PROTEGIDA, headers=_con(token)).status_code == 401

    def test_de_otro_entorno_devuelve_401(self, client, usuario):
        """Misma clave, otra audiencia: un token de staging no vale aquí."""
        token = _firmar(_claims_de_access(usuario["id"], aud="dividi-staging"))
        assert client.get(RUTA_PROTEGIDA, headers=_con(token)).status_code == 401

    def test_de_otro_emisor_devuelve_401(self, client, usuario):
        token = _firmar(_claims_de_access(usuario["id"], iss="otra-api"))
        assert client.get(RUTA_PROTEGIDA, headers=_con(token)).status_code == 401

    def test_sin_audiencia_devuelve_401(self, client, usuario):
        """Un access de antes de este cambio ya no vale: la app refresca sola."""
        token = _firmar(_claims_de_access(usuario["id"], aud=None, iss=None))
        assert client.get(RUTA_PROTEGIDA, headers=_con(token)).status_code == 401

    def test_un_refresh_no_sirve_para_entrar(self, client, usuario):
        emitido = create_refresh_token(usuario["id"])
        assert client.get(RUTA_PROTEGIDA, headers=_con(emitido.token)).status_code == 401


class TestAlgoritmo:
    def test_alg_none_devuelve_401(self, client, usuario):
        """El token sin firma del manual de ataques a JWT."""
        token = jwt.encode(_claims_de_access(usuario["id"]), key=None, algorithm="none")
        assert client.get(RUTA_PROTEGIDA, headers=_con(token)).status_code == 401

    def test_otro_algoritmo_simetrico_devuelve_401(self, client, usuario):
        token = _firmar(_claims_de_access(usuario["id"]), algoritmo="HS512")
        assert client.get(RUTA_PROTEGIDA, headers=_con(token)).status_code == 401

    def test_la_configuracion_no_admite_none(self):
        with pytest.raises(ValueError):
            settings.__class__(
                database_url="sqlite://",
                secret_key="clave-de-pruebas-no-usar-en-produccion-0123456789",
                algorithm="none",
            )


class TestRefreshToken:
    def test_el_token_nuevo_lleva_emisor_y_audiencia(self, usuario):
        datos = decode_token(create_access_token(usuario["id"]))
        assert datos["iss"] == settings.jwt_issuer
        assert datos["aud"] == settings.jwt_audience

    def test_un_refresh_antiguo_sin_audiencia_sigue_valiendo(self, client, usuario):
        """Compatibilidad deliberada: si no, todos vuelven al login.

        Se firma a mano con la forma exacta que tenían los refresh emitidos
        antes de este cambio: `jti` sí, `iss`/`aud` no.
        """
        claims = decode_token(usuario["refresh"], exigir_procedencia=False)
        claims.pop("iss", None)
        claims.pop("aud", None)
        antiguo = _firmar(claims)

        respuesta = client.post("/auth/refresh", json={"refresh_token": antiguo})

        assert respuesta.status_code == 200, respuesta.text

    def test_un_refresh_con_audiencia_ajena_no_vale(self, client, usuario):
        claims = decode_token(usuario["refresh"], exigir_procedencia=False)
        claims["aud"] = "dividi-staging"

        respuesta = client.post("/auth/refresh", json={"refresh_token": _firmar(claims)})

        assert respuesta.status_code == 401, respuesta.text
