"""Money precision: strict parsing, limits, and the database backstops."""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError

from app.core.db import engine
from tests.helpers import assert_reconciled, balance, fund, make_account, post_tx, tx_count

HEADERS = {"Content-Type": "application/json"}
MAX = "9999999999999999.99"


def raw_post(client, account_id, amount_json: str, ref: str):
    """Send the amount exactly as written, bypassing Python's float handling."""
    body = '{"type":"credit","amount":%s,"reference_id":"%s"}' % (amount_json, ref)
    return client.post(f"/accounts/{account_id}/transactions", content=body, headers=HEADERS)


# ---------- parsing is strict ----------
@pytest.mark.parametrize("amount", ["1_000.00", "1e2", ".5", "١٢٣"])
def test_malformed_decimal_strings_are_rejected(client, amount):
    acc = make_account(client)
    r = post_tx(client, acc, "credit", amount, "X")
    assert r.status_code == 422, repr(amount)
    assert r.json()["error"]["code"] == "INVALID_AMOUNT"
    assert tx_count(acc) == 0


@pytest.mark.parametrize(
    "sent,stored", [("10", "10.00"), ("007.50", "7.50"), ("10.000", "10.00")]
)
def test_plain_decimal_strings_are_normalized(client, sent, stored):
    acc = make_account(client)
    r = post_tx(client, acc, "credit", sent, "X")
    assert r.status_code == 201
    assert r.json()["amount"] == stored


# ---------- no silent precision loss or overflow ----------
def test_amounts_that_cannot_be_stored_exactly_are_rejected(client):
    acc = make_account(client)

    # JSON numbers above the float-safe range may already have lost digits.
    assert raw_post(client, acc, "1234567890123456.78", "F1").status_code == 422
    # A float with more decimal places than money can hold.
    assert raw_post(client, acc, "0.30000000000000004", "F2").status_code == 422
    # 17 integer digits do not fit NUMERIC(18,2).
    assert post_tx(client, acc, "credit", "10000000000000000", "F3").status_code == 422

    assert tx_count(acc) == 0


def test_large_amount_is_exact_when_sent_as_a_string(client):
    acc = make_account(client)
    r = post_tx(client, acc, "credit", "1234567890123456.78", "S1")
    assert r.status_code == 201
    assert r.json()["amount"] == "1234567890123456.78"
    assert balance(client, acc) == "1234567890123456.78"
    assert_reconciled()


def test_decimal_accumulation_is_exact(client):
    acc = make_account(client)
    for i in range(100):
        assert post_tx(client, acc, "credit", "0.10", f"T{i}").status_code == 201
    assert balance(client, acc) == "10.00"  # floats would give 9.99999999999998
    assert_reconciled()


# ---------- supported balance limit ----------
def test_balance_cannot_exceed_the_supported_limit(client):
    acc = make_account(client)
    assert post_tx(client, acc, "credit", MAX, "MAX").status_code == 201
    assert balance(client, acc) == MAX

    r = post_tx(client, acc, "credit", "0.01", "OVER")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "BALANCE_LIMIT_EXCEEDED"
    assert balance(client, acc) == MAX
    assert tx_count(acc) == 1
    assert_reconciled()


# ---------- the database is the backstop if application code is bypassed ----------
def _exec(sql, **params):
    with engine.begin() as conn:
        conn.execute(text(sql), params)


def test_database_constraints_protect_invariants(client):
    acc = make_account(client)
    fund(client, acc, "10.00")
    base = (
        "INSERT INTO transactions (id, account_id, type, amount, reference_id) "
        "VALUES (:id, :acc, :type, :amount, :ref)"
    )

    def insert(**overrides):
        params = {"id": uuid.uuid4(), "acc": acc, "type": "credit", "amount": "1.00", "ref": "RAW"}
        params.update(overrides)
        _exec(base, **params)

    with pytest.raises(IntegrityError):  # amount must be > 0
        insert(amount="0")
    with pytest.raises(IntegrityError):
        insert(amount="-5")
    with pytest.raises(IntegrityError):  # type must be credit/debit
        insert(type="refund")
    with pytest.raises(IntegrityError):  # blank reference
        insert(ref="   ")
    with pytest.raises(IntegrityError):  # unique (account_id, reference_id)
        insert(ref="FUND")
    with pytest.raises(IntegrityError):  # unknown account
        insert(acc=uuid.uuid4())
    with pytest.raises(IntegrityError):  # balance can never go negative
        _exec("UPDATE accounts SET balance = -0.01 WHERE id = :a", a=acc)
    with pytest.raises(IntegrityError):  # blank name
        _exec("INSERT INTO accounts (id, name) VALUES (:i, '  ')", i=uuid.uuid4())
    with pytest.raises(DataError):  # NUMERIC(18,2) overflow
        _exec("UPDATE accounts SET balance = 10000000000000000 WHERE id = :a", a=acc)
    assert balance(client, acc) == "10.00"
