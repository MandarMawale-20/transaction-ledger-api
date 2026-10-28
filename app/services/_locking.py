"""The one place that takes account row locks.

Lock order matters: two transfers that lock the same two accounts in opposite
orders (A then B, B then A) deadlock. To rule that out we lock **one account per
statement, in a fixed global order** (ascending UUID).

This deliberately does not rely on `SELECT ... WHERE id IN (...) ORDER BY id
FOR UPDATE`. In PostgreSQL that usually locks in sorted order, but it is a
property of the query plan, not something SQL guarantees. One statement per
lock makes the order true by construction.
"""
import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AccountNotFound
from app.models import Account


def lock_accounts(db: Session, account_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Account]:
    ordered = sorted(set(account_ids), key=lambda u: u.int)
    locked: dict[uuid.UUID, Account] = {}
    missing: list[str] = []
    for account_id in ordered:
        account = db.execute(
            select(Account)
            .where(Account.id == account_id)
            .with_for_update()
            .execution_options(populate_existing=True)  # re-read the row we now own
        ).scalar_one_or_none()
        if account is None:
            missing.append(str(account_id))
        else:
            locked[account_id] = account
    if missing:
        raise AccountNotFound(
            "Account not found: " + ", ".join(missing), {"account_ids": missing}
        )
    return locked
