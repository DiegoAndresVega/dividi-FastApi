"""Freno de la fuerza bruta por cuenta, no solo por IP.

El límite de slowapi es por dirección: frena a quien martillea desde una, y de
paso castiga a todo un NAT compartido por culpa de uno. Lo que no cubre es lo
contrario, que es lo que de verdad se busca al atacar una cuenta concreta:
repartir los intentos entre muchas IPs.

Aquí se cuenta por cuenta. Pasado el umbral, cada fallo impone una espera que
se duplica y tiene tope, así que el ataque queda reducido a unos pocos intentos
por hora y la cuenta se desbloquea sola: nadie tiene que tocar nada, y no hay
un «desbloquéame» del que abusar.

Se cuenta igual para un email que no existe. Si solo se frenaran las cuentas
reales, el freno respondería a la pregunta que no debe responder: si ese correo
está registrado aquí.
"""

import hashlib
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import settings
from app.models import LoginAttempt
from app.models.refresh_token import _en_utc

# Tope al exponente de la duplicación. La espera ya está acotada por
# `login_espera_maxima_segundos`; esto evita calcular 2**5000 para quien lleve
# cinco mil intentos.
MAXIMO_DUPLICACIONES = 20


def _ahora() -> datetime:
    """Un único sitio del que sale la hora: los tests la adelantan aquí."""
    return datetime.now(timezone.utc)


def _huella(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def _espera_por(fallos: int) -> int:
    """Segundos de espera que corresponden a ese número de fallos seguidos."""
    umbral = settings.login_fallos_antes_de_frenar
    if fallos < umbral:
        return 0
    duplicaciones = min(fallos - umbral, MAXIMO_DUPLICACIONES)
    espera = settings.login_espera_base_segundos * 2**duplicaciones
    return min(espera, settings.login_espera_maxima_segundos)


def _olvidado(anotado: LoginAttempt, ahora: datetime) -> bool:
    """Un despiste aislado de hace semanas no suma al de hoy."""
    ventana = timedelta(seconds=settings.login_ventana_olvido_segundos)
    return _en_utc(anotado.ultimo_fallo_at) + ventana < ahora


def espera_restante(db: Session, email: str) -> int:
    """Segundos que faltan para que la cuenta vuelva a admitir intentos.

    0 significa que puede probar. Se consulta ANTES de verificar la contraseña:
    mientras la cuenta está frenada no se comprueba nada, ni siquiera si la
    contraseña era la buena.
    """
    anotado = db.get(LoginAttempt, _huella(email))
    if anotado is None or anotado.bloqueado_hasta is None:
        return 0
    restante = (_en_utc(anotado.bloqueado_hasta) - _ahora()).total_seconds()
    return max(0, math.ceil(restante))


def anotar_fallo(db: Session, email: str) -> int:
    """Suma un fallo y devuelve los segundos de espera que impone (0 si aún no)."""
    ahora = _ahora()
    anotado = db.get(LoginAttempt, _huella(email))
    if anotado is None:
        anotado = LoginAttempt(email_hash=_huella(email), fallos=0, ultimo_fallo_at=ahora)
        db.add(anotado)
    elif _olvidado(anotado, ahora):
        anotado.fallos = 0

    anotado.fallos += 1
    anotado.ultimo_fallo_at = ahora
    espera = _espera_por(anotado.fallos)
    anotado.bloqueado_hasta = ahora + timedelta(seconds=espera) if espera else None
    db.flush()
    return espera


def olvidar(db: Session, email: str) -> None:
    """Borra el marcador de esa cuenta: acaba de demostrar que sabe la contraseña."""
    db.execute(delete(LoginAttempt).where(LoginAttempt.email_hash == _huella(email)))


def limpiar_caducados(db: Session) -> None:
    """Tira las filas que ya no cuentan para nada.

    Cada email tecleado deja una fila, exista la cuenta o no. Sin esta poda la
    tabla crece con todo lo que pruebe un atacante.
    """
    limite = _ahora() - timedelta(seconds=settings.login_ventana_olvido_segundos)
    db.execute(delete(LoginAttempt).where(LoginAttempt.ultimo_fallo_at < limite))
