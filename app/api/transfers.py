from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas import TransactionOut, TransferCreate, TransferOut
from app.services import transfer_service

router = APIRouter(prefix="/transfers", tags=["transfers"])


@router.post(
    "",
    response_model=TransferOut,
    status_code=201,
    responses={200: {"description": "Duplicate reference_id with an identical request: original returned."}},
)
def create_transfer(payload: TransferCreate, response: Response, db: Session = Depends(get_db)):
    """Move money atomically between two accounts."""
    transfer, legs, duplicate = transfer_service.create_transfer(db, payload)
    if duplicate:
        response.status_code = 200
    return TransferOut(
        id=transfer.id,
        from_account_id=transfer.from_account_id,
        to_account_id=transfer.to_account_id,
        amount=transfer.amount,
        description=transfer.description,
        reference_id=transfer.reference_id,
        created_at=transfer.created_at,
        transactions=[TransactionOut.model_validate(leg) for leg in legs],
        duplicate=duplicate,
    )
