"""Copia de los datos personales de un usuario (RGPD, artículos 15 y 20).

Devuelve un diccionario listo para servir como JSON: formato abierto, legible
por una máquina y por una persona, que es lo que pide el derecho de
portabilidad.

Del grupo se incluye lo que afecta a quien lo pide (sus gastos, su parte, sus
pagos) con el nombre que los demás miembros tienen **dentro del grupo**, porque
sin eso los importes no se entienden. No se incluye nada de la vida privada de
los demás: ni su email, ni sus gastos personales, ni sus ahorros.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Expense,
    ExpenseSplit,
    Friendship,
    GroupMember,
    Payment,
    PersonalExpense,
    SavingsPlan,
    User,
    UserBudget,
    UserFinance,
)

AVISO = (
    "Copia de los datos personales asociados a esta cuenta en Dividi, "
    "entregada conforme a los artículos 15 y 20 del RGPD."
)


def exportar(db: Session, user: User) -> dict:
    return {
        "generado_el": _fecha(datetime.now(timezone.utc)),
        "aviso": AVISO,
        "perfil": _perfil(user),
        "finanzas": _finanzas(db, user),
        "gastos_personales": _gastos_personales(db, user),
        "planes_de_ahorro": _planes_de_ahorro(db, user),
        "amistades": _amistades(db, user),
        "grupos": _grupos(db, user),
    }


def _dinero(valor: Optional[Decimal]) -> Optional[str]:
    # Como texto y no como número: un float redondea los céntimos, y esto es
    # una copia que alguien puede querer cuadrar contra su banco.
    return None if valor is None else str(valor)


def _fecha(valor: Optional[datetime]) -> Optional[str]:
    return None if valor is None else valor.isoformat()


def _perfil(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "created_at": _fecha(user.created_at),
    }


def _finanzas(db: Session, user: User) -> dict:
    finanzas = db.get(UserFinance, user.id)
    presupuestos = db.scalars(
        select(UserBudget).where(UserBudget.user_id == user.id)
    ).all()
    return {
        "monthly_income": _dinero(finanzas.monthly_income) if finanzas else None,
        "presupuestos": [
            {"category": p.category, "limit_amount": _dinero(p.limit_amount)}
            for p in presupuestos
        ],
    }


def _gastos_personales(db: Session, user: User) -> list[dict]:
    gastos = db.scalars(
        select(PersonalExpense)
        .where(PersonalExpense.user_id == user.id)
        .order_by(PersonalExpense.created_at)
    ).all()
    return [
        {
            "description": g.description,
            "amount": _dinero(g.amount),
            "category": g.category,
            "created_at": _fecha(g.created_at),
        }
        for g in gastos
    ]


def _planes_de_ahorro(db: Session, user: User) -> list[dict]:
    planes = db.scalars(
        select(SavingsPlan)
        .where(SavingsPlan.user_id == user.id)
        .order_by(SavingsPlan.created_at)
    ).all()
    return [
        {
            "name": plan.name,
            "target_amount": _dinero(plan.target_amount),
            "monthly_amount": _dinero(plan.monthly_amount),
            "saved_amount": _dinero(plan.saved_amount),
            "movimientos": [
                {
                    "kind": entrada.kind.value,
                    "amount": _dinero(entrada.amount),
                    "period": entrada.period,
                    "created_at": _fecha(entrada.created_at),
                }
                for entrada in plan.entries
            ],
        }
        for plan in planes
    ]


def _amistades(db: Session, user: User) -> list[dict]:
    amistades = db.scalars(
        select(Friendship).where(
            (Friendship.requester_id == user.id)
            | (Friendship.addressee_id == user.id)
        )
    ).all()
    return [
        {
            "quien_la_pidio": "yo" if a.requester_id == user.id else "la otra persona",
            "status": a.status.value,
            "created_at": _fecha(a.created_at),
            "responded_at": _fecha(a.responded_at),
        }
        for a in amistades
    ]


def _grupos(db: Session, user: User) -> list[dict]:
    memberships = db.scalars(
        select(GroupMember).where(GroupMember.user_id == user.id)
    ).all()
    return [_grupo(db, m) for m in memberships]


def _grupo(db: Session, membership: GroupMember) -> dict:
    grupo = membership.group
    nombres = {m.id: m.display_name for m in grupo.members}
    return {
        "name": grupo.name,
        "default_currency": grupo.default_currency,
        "created_at": _fecha(grupo.created_at),
        "mi_nombre_en_el_grupo": membership.display_name,
        "mi_rol": membership.role.value,
        "mi_porcentaje": _dinero(membership.default_percentage),
        "gastos": _gastos_del_grupo(db, membership, nombres),
        "pagos": _pagos_del_grupo(db, membership, nombres),
    }


def _gastos_del_grupo(
    db: Session, membership: GroupMember, nombres: dict
) -> list[dict]:
    gastos = db.scalars(
        select(Expense)
        .where(Expense.group_id == membership.group_id)
        .order_by(Expense.created_at)
    ).all()
    partes = {
        (s.expense_id): s
        for s in db.scalars(
            select(ExpenseSplit).where(ExpenseSplit.group_member_id == membership.id)
        ).all()
    }
    return [
        {
            "description": g.description,
            "amount": _dinero(g.amount),
            "currency": g.currency,
            "category": g.category,
            "created_at": _fecha(g.created_at),
            "pagado_por": nombres.get(g.paid_by_id),
            "lo_cree_yo": g.created_by_id == membership.user_id,
            "mi_parte": _dinero(
                partes[g.id].computed_amount if g.id in partes else None
            ),
        }
        for g in gastos
    ]


def _pagos_del_grupo(
    db: Session, membership: GroupMember, nombres: dict
) -> list[dict]:
    pagos = db.scalars(
        select(Payment)
        .where(Payment.group_id == membership.group_id)
        .order_by(Payment.paid_at)
    ).all()
    return [
        {
            "amount": _dinero(p.amount),
            "de": nombres.get(p.from_member_id),
            "a": nombres.get(p.to_member_id),
            "paid_at": _fecha(p.paid_at),
            "note": p.note,
        }
        for p in pagos
        if membership.id in (p.from_member_id, p.to_member_id)
    ]
