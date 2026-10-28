import enum
import math
import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)


class TransactionType(str, enum.Enum):
    credit = "credit"
    debit = "debit"


# Money is a Decimal internally and always serialised as a 2-decimal string
# ("500.00") so clients never deal with floating point.
Money = Annotated[
    Decimal, PlainSerializer(lambda v: f"{v:.2f}", return_type=str, when_used="json")
]

# JSON numbers reach us as 64-bit floats, which hold ~15 significant digits
# exactly. Below 1e13 with 2 decimals (15 digits) a float round-trips faithfully;
# above that the digits the client typed may already be gone, so we refuse
# rather than silently store a different amount.
_MAX_FLOAT_AMOUNT = 1e13
_PLAIN_DECIMAL = re.compile(r"[0-9]+(\.[0-9]+)?")


def _strict_amount(value):
    if isinstance(value, bool):
        raise ValueError("amount must be a number")
    if isinstance(value, str):
        # Plain ASCII decimals only. Python's Decimal() would also accept
        # "1_000", "1e2", "+5", ".5" and non-ASCII digits like "\u0661\u0662\u0663".
        text = value.strip()
        if not _PLAIN_DECIMAL.fullmatch(text):
            raise ValueError("amount must be a plain decimal number such as 10.50")
        return text
    if isinstance(value, float):
        if not math.isfinite(value) or abs(value) >= _MAX_FLOAT_AMOUNT:
            raise ValueError(
                "amounts of 10,000,000,000,000 or more must be sent as a string to avoid precision loss"
            )
    return value


# Request-side amount: > 0, at most 18 digits total, at most 2 decimal places.
Amount = Annotated[
    Decimal,
    BeforeValidator(_strict_amount),
    Field(gt=0, max_digits=18, decimal_places=2),
]
ReferenceId = Annotated[str, Field(min_length=1, max_length=128)]


class _Request(BaseModel):
    # extra="forbid": unknown fields (e.g. a client-supplied "balance") are rejected.
    # str_strip_whitespace: "PAY-1" and "PAY-1 " are the same idempotency key.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _blank_to_none(value: str | None) -> str | None:
    return value or None


# ---------- accounts ----------
class AccountCreate(_Request):
    name: Annotated[str, Field(min_length=1, max_length=255)]


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    balance: Money
    created_at: datetime


class BalanceOut(BaseModel):
    account_id: uuid.UUID
    balance: Money


class AccountPage(BaseModel):
    items: list[AccountOut]
    total: int
    limit: int
    offset: int


# ---------- transactions ----------
class TransactionCreate(_Request):
    type: TransactionType
    amount: Amount
    description: Annotated[str | None, Field(max_length=500)] = None
    reference_id: ReferenceId

    _normalise_description = field_validator("description")(_blank_to_none)


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    account_id: uuid.UUID
    type: TransactionType
    amount: Money
    description: str | None
    reference_id: str
    transfer_id: uuid.UUID | None
    created_at: datetime


class TransactionCreateOut(TransactionOut):
    duplicate: bool = False


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    total: int
    limit: int
    offset: int


# ---------- transfers ----------
class TransferCreate(_Request):
    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount: Amount
    description: Annotated[str | None, Field(max_length=500)] = None
    reference_id: ReferenceId

    _normalise_description = field_validator("description")(_blank_to_none)

    @model_validator(mode="after")
    def _accounts_differ(self):
        if self.from_account_id == self.to_account_id:
            raise ValueError("from_account_id and to_account_id must be different")
        return self


class TransferOut(BaseModel):
    id: uuid.UUID
    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount: Money
    description: str | None
    reference_id: str
    created_at: datetime
    transactions: list[TransactionOut]
    duplicate: bool = False
