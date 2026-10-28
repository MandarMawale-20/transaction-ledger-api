import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas import (
    TransactionCreate,
    TransactionCreateOut,
    TransactionOut,
    TransactionPage,
    TransactionType,
)
from app.services import ledger_service

router = APIRouter(prefix="/accounts", tags=["transactions"])


@router.post(
    "/{account_id}/transactions",
    response_model=TransactionCreateOut,
    status_code=201,
    responses={200: {"description": "Duplicate reference_id with an identical request: original returned."}},
)
def create_transaction(
    account_id: uuid.UUID,
    payload: TransactionCreate,
    response: Response,
    db: Session = Depends(get_db),
):
    """Post a credit or debit. An identical retry returns the original with 200."""
    txn, duplicate = ledger_service.create_transaction(db, account_id, payload)
    if duplicate:
        response.status_code = 200
    out = TransactionCreateOut.model_validate(txn)
    out.duplicate = duplicate
    return out


@router.get("/{account_id}/transactions", response_model=TransactionPage)
def list_transactions(
    account_id: uuid.UUID,
    type: TransactionType | None = Query(None, description="credit or debit; omit for both"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List an account's transactions, newest first."""
    items, total = ledger_service.list_transactions(db, account_id, type, limit, offset)
    return TransactionPage(
        items=[TransactionOut.model_validate(t) for t in items],
        total=total,
        limit=limit,
        offset=offset,
    )
