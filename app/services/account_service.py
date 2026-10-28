import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AccountNotFound
from app.models import Account
from app.schemas import AccountCreate


def create_account(db: Session, payload: AccountCreate) -> Account:
    # The client can never set the balance: it is always created as 0.
    with db.begin():
        account = Account(name=payload.name, balance=Decimal("0"))
        db.add(account)
        db.flush()
        return account


def list_accounts(db: Session, limit: int, offset: int) -> tuple[list[Account], int]:
    """Newest first. `id` is only a tie-breaker, so paging stays deterministic."""
    total = db.execute(select(func.count()).select_from(Account)).scalar_one()
    items = (
        db.execute(
            select(Account)
            .order_by(Account.created_at.desc(), Account.id)
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return list(items), total


def require_account(db: Session, account_id: uuid.UUID) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise AccountNotFound(
            f"Account not found: {account_id}", {"account_ids": [str(account_id)]}
        )
    return account
