"""Alta, rotación y revocación de refresh tokens.

La regla que gobierna todo esto: un refresh token vale exactamente un uso. Al
gastarlo se emite el siguiente de la misma familia y el anterior queda marcado.
Si un token ya gastado reaparece, alguien tiene una copia —y no hay forma de
distinguir al dueño del ladrón—, así que se cae la familia entera.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, distinct, func, select, update
from sqlalchemy.orm import Session

from app.models import RefreshToken
from app.models.refresh_token import _en_utc
from app.security import create_refresh_token


# Margen para la carrera benigna: la app lanza varias peticiones a la vez y
# todas se topan con el access token caducado, así que varias intentan refrescar
# con el MISMO token antes de que ninguna haya guardado el nuevo. Eso no es un
# robo. Sin este margen, abrir una pantalla que carga tres cosas en paralelo
# cerraría la sesión, y en las versiones de la app ya instaladas no hay forma de
# arreglarlo desde aquí. Un ladrón que replique el token días después sí cae.
GRACIA_REUTILIZACION = timedelta(seconds=10)


class RefreshTokenInvalido(Exception):
    """El token no existe, ya se usó, se revocó o caducó."""


class RefreshTokenReutilizado(RefreshTokenInvalido):
    """Un token ya gastado reapareció fuera del margen: alguien tiene una copia.

    Subclase de RefreshTokenInvalido para que quien solo quiera rechazar la
    petición siga capturando una sola cosa. Se distingue porque esto no es un
    token caducado más: es la única señal de robo que da el sistema, y merece
    su propio evento en el registro de seguridad.
    """


def emitir(db: Session, user_id: uuid.UUID, family_id: uuid.UUID | None = None) -> str:
    """Firma un refresh token nuevo y lo anota como vivo.

    Sin `family_id` empieza una familia: eso es un login. Con él, continúa la
    cadena de rotaciones que arrancó aquel login.
    """
    emitido = create_refresh_token(user_id)
    db.add(
        RefreshToken(
            jti=emitido.jti,
            user_id=user_id,
            family_id=family_id or uuid.uuid4(),
            expires_at=emitido.expires_at,
        )
    )
    return emitido.token


def rotar(db: Session, jti: uuid.UUID) -> tuple[uuid.UUID, str]:
    """Gasta el token indicado y devuelve `(user_id, token nuevo)`.

    Lanza `RefreshTokenInvalido` si no sirve. Cuando el motivo es que ya estaba
    gastado, además tumba la familia antes de lanzar.
    """
    anotado = db.get(RefreshToken, jti)
    if anotado is None:
        raise RefreshTokenInvalido

    if anotado.used_at is not None:
        if datetime.now(timezone.utc) - _en_utc(anotado.used_at) > GRACIA_REUTILIZACION:
            # reutilización de verdad: la copia puede estar en cualquiera de los
            # dos lados, así que se cierra la sesión entera y ambos al login
            revocar_familia(db, anotado.family_id)
            raise RefreshTokenReutilizado
        if anotado.revoked_at is not None:
            # la sesión se cerró entre medias (logout, cambio de contraseña): el
            # margen es para la carrera benigna, no para sacar un token nuevo de
            # una sesión que ya no existe
            raise RefreshTokenInvalido
        # dentro del margen: se le da un token nuevo de la misma familia y no
        # pasa nada. Los dos que corrían acaban con uno válido cada uno
        return anotado.user_id, emitir(db, anotado.user_id, family_id=anotado.family_id)

    if not anotado.is_usable:
        raise RefreshTokenInvalido

    anotado.used_at = datetime.now(timezone.utc)
    return anotado.user_id, emitir(db, anotado.user_id, family_id=anotado.family_id)


def revocar_familia(db: Session, family_id: uuid.UUID) -> None:
    """Invalida la cadena entera nacida de un login."""
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )


def revocar_usuario(db: Session, user_id: uuid.UUID) -> int:
    """Cierra todas las sesiones de un usuario, en todos sus dispositivos.

    Devuelve cuántas seguían abiertas. Cuenta familias con un token todavía
    utilizable, no filas: cada rotación deja atrás una fila gastada.
    """
    ahora = datetime.now(timezone.utc)
    abiertas = db.scalar(
        select(func.count(distinct(RefreshToken.family_id))).where(
            RefreshToken.user_id == user_id,
            RefreshToken.used_at.is_(None),
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > ahora,
        )
    )
    # se revocan también las gastadas: dentro del margen de gracia todavía
    # podrían dar un token nuevo
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=ahora)
    )
    return abiertas or 0


def limpiar_caducados(db: Session) -> None:
    """Borra lo que ya no puede servir para nada.

    Se emite un token por cada rotación y duran un año, así que sin esto la
    tabla solo crece. Un token caducado no se acepta ni aunque siga anotado, de
    modo que su fila no aporta nada.
    """
    db.execute(delete(RefreshToken).where(RefreshToken.expires_at < datetime.now(timezone.utc)))
