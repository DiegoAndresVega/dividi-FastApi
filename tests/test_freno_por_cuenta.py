"""Freno de la fuerza bruta contra una cuenta concreta.

El límite por IP frena a quien martillea desde una dirección. Estos tests
miran la otra cara: muchas IPs distintas probando contraseñas contra el mismo
email, y que frenar una cuenta no cuente nada sobre si ese email existe.
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import login_attempt_service as freno

EMAIL = "ana@example.com"
CONTRASENA = "password123"
OTRO_EMAIL = "sin-cuenta@example.com"


def _registrar(client):
    respuesta = client.post(
        "/auth/register",
        json={"email": EMAIL, "password": CONTRASENA, "name": "Ana"},
    )
    assert respuesta.status_code == 201, respuesta.text


def _desde(ip: str) -> TestClient:
    """Un cliente que la API ve llegar desde esa IP."""
    return TestClient(app, client=(ip, 51000))


def _intentar(cliente, email=EMAIL, contrasena="equivocada"):
    return cliente.post(
        "/auth/login", data={"username": email, "password": contrasena}
    )


def _fallar_n_veces(veces: int, email=EMAIL) -> list:
    return [
        _intentar(_desde(f"203.0.113.{numero}"), email=email)
        for numero in range(1, veces + 1)
    ]


@pytest.fixture
def reloj(monkeypatch):
    """Permite adelantar la hora que ve el freno, sin esperas reales."""
    desfase = {"segundos": 0}
    original = freno._ahora

    def _ahora_movido():
        return original() + timedelta(seconds=desfase["segundos"])

    monkeypatch.setattr(freno, "_ahora", _ahora_movido)

    def adelantar(segundos: int):
        desfase["segundos"] += segundos

    return adelantar


def test_veinte_intentos_fallidos_desde_ips_distintas_quedan_frenados(client):
    _registrar(client)
    umbral = settings.login_fallos_antes_de_frenar

    respuestas = _fallar_n_veces(20)

    # los primeros son un fallo de contraseña normal; a partir del umbral la
    # cuenta deja de admitir intentos, venga la petición de la IP que venga
    assert [r.status_code for r in respuestas[:umbral]] == [401] * umbral
    assert {r.status_code for r in respuestas[umbral:]} == {429}
    assert respuestas[-1].headers["Retry-After"]


def test_la_contrasena_correcta_no_entra_mientras_la_cuenta_esta_frenada(client):
    _registrar(client)
    _fallar_n_veces(settings.login_fallos_antes_de_frenar)

    respuesta = _intentar(_desde("198.51.100.9"), contrasena=CONTRASENA)

    assert respuesta.status_code == 429


def test_un_email_sin_cuenta_se_frena_igual_que_uno_real(client):
    """Si solo se frenaran las cuentas reales, el 429 sería un buscador de emails."""
    _registrar(client)

    reales = _fallar_n_veces(8)
    inexistentes = _fallar_n_veces(8, email=OTRO_EMAIL)

    assert [(r.status_code, r.json()) for r in reales] == [
        (r.status_code, r.json()) for r in inexistentes
    ]


def test_frenar_una_cuenta_no_frena_a_las_demas(client):
    _registrar(client)
    otra = "bea@example.com"
    client.post(
        "/auth/register",
        json={"email": otra, "password": CONTRASENA, "name": "Bea"},
    )
    _fallar_n_veces(10)

    respuesta = _intentar(_desde("192.0.2.5"), email=otra, contrasena=CONTRASENA)

    assert respuesta.status_code == 200


def test_un_login_correcto_olvida_los_fallos_anteriores(client):
    _registrar(client)
    _fallar_n_veces(settings.login_fallos_antes_de_frenar - 1)

    assert _intentar(_desde("192.0.2.7"), contrasena=CONTRASENA).status_code == 200

    # el marcador vuelve a cero: quedan otra vez todos los intentos por delante
    siguientes = _fallar_n_veces(settings.login_fallos_antes_de_frenar - 1)
    assert {r.status_code for r in siguientes} == {401}


def test_pasada_la_espera_la_cuenta_vuelve_a_admitir_la_contrasena_buena(client, reloj):
    _registrar(client)
    _fallar_n_veces(settings.login_fallos_antes_de_frenar)
    assert _intentar(_desde("192.0.2.8"), contrasena=CONTRASENA).status_code == 429

    reloj(settings.login_espera_base_segundos + 1)

    # se desbloquea sola con el tiempo: nadie tiene que tocar la base de datos
    assert _intentar(_desde("192.0.2.8"), contrasena=CONTRASENA).status_code == 200


def test_la_espera_se_duplica_con_cada_fallo_y_tiene_tope(db_session):
    umbral = settings.login_fallos_antes_de_frenar
    esperas = [freno.anotar_fallo(db_session, EMAIL) for _ in range(umbral + 12)]

    assert esperas[: umbral - 1] == [0] * (umbral - 1)
    assert esperas[umbral - 1] == settings.login_espera_base_segundos
    assert esperas[umbral] == settings.login_espera_base_segundos * 2
    assert esperas[-1] == settings.login_espera_maxima_segundos


def test_los_fallos_se_olvidan_pasada_la_ventana(db_session, reloj):
    for _ in range(settings.login_fallos_antes_de_frenar - 1):
        freno.anotar_fallo(db_session, EMAIL)

    reloj(settings.login_ventana_olvido_segundos + 1)

    # un despiste de hace un mes no puede sumar al de hoy
    assert freno.anotar_fallo(db_session, EMAIL) == 0


def test_cambiar_la_contrasena_fallando_la_actual_tambien_frena(client):
    _registrar(client)
    respuesta = client.post(
        "/auth/login", data={"username": EMAIL, "password": CONTRASENA}
    )
    cabeceras = {"Authorization": f"Bearer {respuesta.json()['access_token']}"}
    cuerpo = {"current_password": "equivocada", "new_password": "otraclave123"}

    respuestas = [
        client.post("/me/password", json=cuerpo, headers=cabeceras)
        for _ in range(settings.login_fallos_antes_de_frenar + 1)
    ]

    assert respuestas[0].status_code == 400
    assert respuestas[-1].status_code == 429
    # y el freno es el mismo marcador que el del login
    assert _intentar(_desde("192.0.2.11"), contrasena=CONTRASENA).status_code == 429


def test_el_email_no_se_guarda_en_claro_en_la_tabla_de_intentos(db_session):
    """En esa tabla acaban correos de terceros que ni siquiera tienen cuenta."""
    freno.anotar_fallo(db_session, EMAIL)
    db_session.commit()

    from app.models import LoginAttempt

    filas = db_session.query(LoginAttempt).all()
    assert len(filas) == 1
    assert EMAIL not in filas[0].email_hash
