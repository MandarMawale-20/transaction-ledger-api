import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas import AccountCreate, AccountOut, AccountPage, BalanceOut
from app.services import account_service

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.post("", response_model=AccountOut, status_code=201)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)):
    """Create an account with a zero balance."""
    return AccountOut.model_validate(account_service.create_account(db, payload))


@router.get("", response_model=AccountPage)
def list_accounts(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List accounts, newest first."""
    items, total = account_service.list_accounts(db, limit, offset)
    return AccountPage(
        items=[AccountOut.model_validate(a) for a in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{account_id}", response_model=AccountOut)
def get_account(account_id: uuid.UUID, db: Session = Depends(get_db)):
    """Return one account."""
    return AccountOut.model_validate(account_service.require_account(db, account_id))


@router.get("/{account_id}/balance", response_model=BalanceOut)
def get_balance(account_id: uuid.UUID, db: Session = Depends(get_db)):
    """Return an account's current balance."""
    account = account_service.require_account(db, account_id)
    return BalanceOut(account_id=account.id, balance=account.balance)
