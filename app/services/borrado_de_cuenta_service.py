"""Borrado de cuenta a petición del usuario (RGPD, artículo 17).

La fila del usuario **no se puede borrar**: los gastos y los pagos de un grupo
compartido apuntan a ella y son también datos de los demás miembros. Borrarla
descuadraría balances ajenos, que es justo lo que el artículo 17.3 no exige
sacrificar.

Lo que se hace, entonces:

- se borra lo que solo era suyo (gastos personales, nómina, presupuestos,
  planes de ahorro, notificaciones, amistades y sesiones);
- en cada grupo, su miembro se desvincula de la cuenta y pasa a llamarse
  «Usuario eliminado», conservando los importes;
- de su fila queda una lápida: sin email real, sin nombre y sin contraseña
  utilizable, marcada con `deleted_at`.

Las invitaciones que **creó** se quedan como están: su campo `email` reserva
el código para otra persona, y vaciarlo lo abriría a cualquiera. La que
**canjeó** sí se limpia: ahí el email guardado es el suyo, su invitador lo ve
en `GET /invitations`, y vaciarlo no reabre nada porque `validate_code` corta
en `is_used` antes de comparar el email.
"""

import secrets
from datetime import datetime, timezone

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Friendship,
    GroupMember,
    Invitation,
    Notification,
    PersonalExpense,
    SavingsPlan,
    User,
    UserBudget,
    UserFinance,
)
from app.security import hash_password
from app.services import login_attempt_service, refresh_token_service

NOMBRE_ANONIMO = "Usuario eliminado"
# RFC 2606 reserva .invalid: ese dominio no existe ni va a existir, así que la
# lápida no puede recibir correo ni colisionar con el email de nadie.
DOMINIO_DE_LAPIDA = "dividi.invalid"


def esta_borrada(user: User) -> bool:
    return user.deleted_at is not None


def anonimizar(db: Session, user: User) -> None:
    """Deja al usuario sin datos personales. No hace commit: lo hace quien llama,
    para que el borrado entero caiga en una sola transacción."""
    _borrar_lo_que_solo_era_suyo(db, user)
    _desvincular_de_los_grupos(db, user)
    _soltar_la_invitacion_que_canjeo(db, user)
    _convertir_en_lapida(db, user)


def _borrar_lo_que_solo_era_suyo(db: Session, user: User) -> None:
    # Los planes se borran uno a uno y no en bloque: sus movimientos cuelgan
    # de una relación con delete-orphan, y un DELETE masivo se la salta.
    for plan in db.scalars(
        select(SavingsPlan).where(SavingsPlan.user_id == user.id)
    ).all():
        db.delete(plan)

    for modelo in (PersonalExpense, UserBudget, UserFinance, Notification):
        db.execute(delete(modelo).where(modelo.user_id == user.id))

    db.execute(
        delete(Friendship).where(
            or_(
                Friendship.requester_id == user.id,
                Friendship.addressee_id == user.id,
            )
        )
    )

    refresh_token_service.revocar_usuario(db, user.id)
    # El marcador de fuerza bruta va por huella del email; hay que soltarlo
    # mientras el email de verdad todavía está puesto.
    login_attempt_service.olvidar(db, user.email)


def _desvincular_de_los_grupos(db: Session, user: User) -> None:
    """El miembro sobrevive al usuario, porque los importes son del grupo.

    `invited_email` tiene que quedar vacío: el registro vincula miembros
    pendientes por esa columna (ver `auth.register`), así que dejarla puesta
    metería en estos grupos a quien reutilizase la dirección.
    """
    for membership in db.scalars(
        select(GroupMember).where(GroupMember.user_id == user.id)
    ).all():
        membership.user_id = None
        membership.invited_email = None
        membership.display_name = NOMBRE_ANONIMO


def _soltar_la_invitacion_que_canjeo(db: Session, user: User) -> None:
    """El email con el que se le invitó es suyo, y su invitador lo ve listado.

    La fila se queda (es del invitador, y el código debe seguir consumido);
    lo que se va es la dirección.
    """
    for invitacion in db.scalars(
        select(Invitation).where(Invitation.used_by_id == user.id)
    ).all():
        invitacion.email = None


def _convertir_en_lapida(db: Session, user: User) -> None:
    user.email = f"borrado-{user.id}@{DOMINIO_DE_LAPIDA}"
    user.name = NOMBRE_ANONIMO
    # Un hash de un secreto que no se guarda en ninguna parte: nadie puede
    # acertarlo, y deja la columna con un bcrypt válido en vez de un valor
    # raro que reviente al verificarlo.
    user.hashed_password = hash_password(secrets.token_urlsafe(32))
    user.deleted_at = datetime.now(timezone.utc)
