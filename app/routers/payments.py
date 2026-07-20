import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, get_group_or_404, require_membership
from app.models import Payment, User
from app.schemas.payment import PaymentCreate, PaymentOut

router = APIRouter(prefix="/groups/{group_id}/payments", tags=["payments"])


@router.post("", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def create_payment(
    group_id: uuid.UUID,
    payload: PaymentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = get_group_or_404(db, group_id)
    require_membership(group, user)

    member_ids = {m.id for m in group.members}
    if payload.from_member_id not in member_ids or payload.to_member_id not in member_ids:
        raise HTTPException(
            status_code=400, detail="Ambos miembros deben pertenecer al grupo"
        )
    if payload.from_member_id == payload.to_member_id:
        raise HTTPException(
            status_code=400, detail="El pagador y el receptor no pueden ser el mismo"
        )

    payment = Payment(
        group_id=group.id,
        from_member_id=payload.from_member_id,
        to_member_id=payload.to_member_id,
        amount=payload.amount,
        paid_at=payload.paid_at or datetime.now(timezone.utc),
        note=payload.note,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


@router.delete("/{payment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_payment(
    group_id: uuid.UUID,
    payment_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Des-salda una cuenta: borra el pago y el balance vuelve a como estaba.

    Los balances se recalculan siempre desde los gastos y los pagos, así que
    basta con eliminar el pago para deshacer el saldado.
    """
    group = get_group_or_404(db, group_id)
    require_membership(group, user)

    payment = db.scalar(
        select(Payment).where(Payment.id == payment_id, Payment.group_id == group.id)
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="Pago no encontrado en el grupo")

    db.delete(payment)
    db.commit()


@router.get("", response_model=list[PaymentOut])
def list_payments(
    group_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = get_group_or_404(db, group_id)
    require_membership(group, user)
    return db.scalars(
        select(Payment)
        .where(Payment.group_id == group.id)
        .order_by(Payment.paid_at.desc())
    ).all()
