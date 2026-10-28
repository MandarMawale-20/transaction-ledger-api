"""Credit / debit processing.

Only this module and transfer_service may change balances or insert ledger
rows, and each owns exactly one database transaction per request.

Per-request protocol (see docs/ARCHITECTURE.md section 8):
  1. lock the account row (SELECT ... FOR UPDATE)
  2. look for an existing (account_id, reference_id)  -> idempotent replay / conflict
  3. check balance for debits
  4. insert the ledger row + update the balance, commit
The UNIQUE (account_id, reference_id) constraint is the last line of defence.
"""
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import InsufficientBalance, ReferenceConflict
from app.core.money import ensure_within_limit
from app.models import Transaction
from app.schemas import TransactionCreate, TransactionType
from app.services import account_service
from app.services._db_utils import constraint_name
from app.services._locking import lock_accounts

UQ_ACCOUNT_REFERENCE = "uq_transactions_account_reference"


def _find_by_reference(
    db: Session, account_id: uuid.UUID, reference_id: str
) -> Transaction | None:
    return db.execute(
        select(Transaction).where(
            Transaction.account_id == account_id,
            Transaction.reference_id == reference_id,
        )
    ).scalar_one_or_none()


def _resolve_duplicate(existing: Transaction, data: TransactionCreate):
    """Same payload -> replay the original. Different payload -> 409."""
    same = (
        existing.type == data.type.value
        and existing.amount == data.amount
        and existing.description == data.description
    )
    if not same:
        raise ReferenceConflict(
            details={"reference_id": existing.reference_id, "transaction_id": str(existing.id)}
        )
    return existing, True


def _apply(db: Session, account_id: uuid.UUID, data: TransactionCreate):
    account = lock_accounts(db, [account_id])[account_id]

    existing = _find_by_reference(db, account_id, data.reference_id)
    if existing is not None:
        return _resolve_duplicate(existing, data)

    if data.type is TransactionType.debit:
        if account.balance < data.amount:
            raise InsufficientBalance(
                details={
                    "balance": f"{account.balance:.2f}",
                    "requested": f"{data.amount:.2f}",
                }
            )
        account.balance = account.balance - data.amount
    else:
        new_balance = account.balance + data.amount
        ensure_within_limit(new_balance)
        account.balance = new_balance

    txn = Transaction(
        account_id=account_id,
        type=data.type.value,
        amount=data.amount,
        description=data.description,
        reference_id=data.reference_id,
    )
    db.add(txn)
    db.flush()
    return txn, False


def create_transaction(
    db: Session, account_id: uuid.UUID, data: TransactionCreate
) -> tuple[Transaction, bool]:
    """Returns (transaction, duplicate)."""
    try:
        with db.begin():
            return _apply(db, account_id, data)
    except IntegrityError as exc:
        if constraint_name(exc) != UQ_ACCOUNT_REFERENCE:
            raise
    # Fallback, normally unreachable because of the row lock: the unique
    # constraint fired. The failed transaction has been rolled back (balance
    # change included), so re-read in a fresh one.
    with db.begin():
        existing = _find_by_reference(db, account_id, data.reference_id)
        if existing is None:
            raise ReferenceConflict()
        return _resolve_duplicate(existing, data)


def list_transactions(
    db: Session,
    account_id: uuid.UUID,
    type_: TransactionType | None,
    limit: int,
    offset: int,
) -> tuple[list[Transaction], int]:
    account_service.require_account(db, account_id)
    filters = [Transaction.account_id == account_id]
    if type_ is not None:
        filters.append(Transaction.type == type_.value)

    total = db.execute(
        select(func.count()).select_from(Transaction).where(*filters)
    ).scalar_one()
    items = (
        db.execute(
            select(Transaction)
            .where(*filters)
            .order_by(Transaction.seq.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return list(items), total
