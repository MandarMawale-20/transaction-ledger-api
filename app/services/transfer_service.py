"""Atomic, idempotent transfers.

One database transaction covers: both account locks, the transfer row, both
ledger legs and both balance updates. Any failure rolls all of it back.

Deadlock avoidance: both accounts are locked through services/_locking.py, one
statement per account in a fixed global order, so A->B and B->A running
concurrently always take locks in the same order.
"""
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import InsufficientBalance, ReferenceConflict
from app.core.money import ensure_within_limit
from app.models import Transaction, Transfer
from app.schemas import TransactionType, TransferCreate
from app.services._db_utils import constraint_name
from app.services._locking import lock_accounts

UQ_TRANSFER_REFERENCE = "uq_transfers_from_reference"
UQ_ACCOUNT_REFERENCE = "uq_transactions_account_reference"


def _find_transfer(db: Session, from_account_id: uuid.UUID, reference_id: str):
    return db.execute(
        select(Transfer).where(
            Transfer.from_account_id == from_account_id,
            Transfer.reference_id == reference_id,
        )
    ).scalar_one_or_none()


def _legs(db: Session, transfer_id: uuid.UUID) -> list[Transaction]:
    return list(
        db.execute(
            select(Transaction)
            .where(Transaction.transfer_id == transfer_id)
            .order_by(Transaction.seq)
        )
        .scalars()
        .all()
    )


def _resolve_duplicate(db: Session, existing: Transfer, data: TransferCreate):
    same = (
        existing.from_account_id == data.from_account_id
        and existing.to_account_id == data.to_account_id
        and existing.amount == data.amount
        and existing.description == data.description
    )
    if not same:
        raise ReferenceConflict(
            details={"reference_id": existing.reference_id, "transfer_id": str(existing.id)}
        )
    return existing, _legs(db, existing.id), True


def _insert_leg(
    db: Session,
    *,
    account_id: uuid.UUID,
    type_: TransactionType,
    amount: Decimal,
    description: str | None,
    reference_id: str,
    transfer_id: uuid.UUID,
) -> Transaction:
    leg = Transaction(
        account_id=account_id,
        type=type_.value,
        amount=amount,
        description=description,
        reference_id=reference_id,
        transfer_id=transfer_id,
    )
    db.add(leg)
    db.flush()
    return leg


def _apply(db: Session, data: TransferCreate):
    by_id = lock_accounts(db, [data.from_account_id, data.to_account_id])

    existing = _find_transfer(db, data.from_account_id, data.reference_id)
    if existing is not None:
        return _resolve_duplicate(db, existing, data)

    source, destination = by_id[data.from_account_id], by_id[data.to_account_id]
    if source.balance < data.amount:
        raise InsufficientBalance(
            details={
                "balance": f"{source.balance:.2f}",
                "requested": f"{data.amount:.2f}",
            }
        )

    destination_balance = destination.balance + data.amount
    ensure_within_limit(destination_balance)

    transfer = Transfer(
        id=uuid.uuid4(),
        from_account_id=data.from_account_id,
        to_account_id=data.to_account_id,
        amount=data.amount,
        reference_id=data.reference_id,
        description=data.description,
    )
    db.add(transfer)
    db.flush()

    # Leg references come from the transfer UUID, never from client input,
    # so they cannot collide with a client-chosen reference_id.
    debit = _insert_leg(
        db,
        account_id=source.id,
        type_=TransactionType.debit,
        amount=data.amount,
        description=data.description,
        reference_id=f"{transfer.id}:out",
        transfer_id=transfer.id,
    )
    credit = _insert_leg(
        db,
        account_id=destination.id,
        type_=TransactionType.credit,
        amount=data.amount,
        description=data.description,
        reference_id=f"{transfer.id}:in",
        transfer_id=transfer.id,
    )
    source.balance = source.balance - data.amount
    destination.balance = destination_balance
    db.flush()
    return transfer, [debit, credit], False


def create_transfer(db: Session, data: TransferCreate):
    """Returns (transfer, legs, duplicate)."""
    try:
        with db.begin():
            return _apply(db, data)
    except IntegrityError as exc:
        if constraint_name(exc) not in (UQ_TRANSFER_REFERENCE, UQ_ACCOUNT_REFERENCE):
            raise
    # Fallback after a rolled-back unique violation (normally unreachable).
    with db.begin():
        existing = _find_transfer(db, data.from_account_id, data.reference_id)
        if existing is None:
            raise ReferenceConflict()
        return _resolve_duplicate(db, existing, data)
