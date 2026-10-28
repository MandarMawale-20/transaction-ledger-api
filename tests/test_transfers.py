import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.core.errors import InsufficientBalance
from app.schemas import TransferCreate
from app.services import transfer_service
from tests.helpers import assert_reconciled, balance, fund, make_account, tx_count


def transfer(client, src, dst, amount, ref, description=None):
    body = {"from_account_id": src, "to_account_id": dst, "amount": amount, "reference_id": ref}
    if description is not None:
        body["description"] = description
    return client.post("/transfers", json=body)


def transfer_rows() -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM transfers")).scalar_one()


def two_accounts(client, a_balance="100.00", b_balance="50.00"):
    a, b = make_account(client, "A"), make_account(client, "B")
    fund(client, a, a_balance)
    if Decimal(b_balance) > 0:  # amounts must be > 0, so zero means "no funding"
        fund(client, b, b_balance)
    return a, b


def _payload(src, dst, amount, ref, description=None):
    return TransferCreate(
        from_account_id=src,
        to_account_id=dst,
        amount=Decimal(amount),
        reference_id=ref,
        description=description,
    )


def test_successful_transfer_moves_money_and_records_both_legs(client):
    a, b = two_accounts(client)

    r = transfer(client, a, b, "30.00", "T1", "rent")
    assert r.status_code == 201
    body = r.json()
    assert body["duplicate"] is False
    assert balance(client, a) == "70.00" and balance(client, b) == "80.00"

    legs = body["transactions"]
    assert len(legs) == 2
    assert {leg["type"] for leg in legs} == {"debit", "credit"}
    assert {leg["account_id"] for leg in legs} == {a, b}
    assert all(leg["amount"] == "30.00" for leg in legs)
    assert all(leg["transfer_id"] == body["id"] for leg in legs)

    # Both legs are visible in their account's history, not just in the response.
    for leg in legs:
        history = client.get(f"/accounts/{leg['account_id']}/transactions").json()
        assert leg["id"] in [t["id"] for t in history["items"]]
    assert_reconciled()


@pytest.mark.parametrize("amount", [0, "1.234", "abc"])
def test_invalid_transfer_amounts_are_rejected(client, amount):
    a, b = two_accounts(client)
    r = transfer(client, a, b, amount, "T1")
    assert r.status_code == 422, amount
    assert r.json()["error"]["code"] == "INVALID_AMOUNT"
    assert transfer_rows() == 0


def test_transfer_to_the_same_account_is_rejected(client):
    a, _ = two_accounts(client)
    r = transfer(client, a, a, "1.00", "T1")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert transfer_rows() == 0


def test_transfer_with_a_missing_account_is_404(client):
    a, _ = two_accounts(client)
    assert transfer(client, a, str(uuid.uuid4()), "1.00", "T1").status_code == 404
    assert transfer(client, str(uuid.uuid4()), a, "1.00", "T2").status_code == 404
    assert balance(client, a) == "100.00"
    assert transfer_rows() == 0


def test_insufficient_transfer_changes_nothing(client):
    a, b = two_accounts(client)
    before = tx_count()

    r = transfer(client, a, b, "100.01", "T1")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "INSUFFICIENT_BALANCE"
    assert balance(client, a) == "100.00" and balance(client, b) == "50.00"
    assert tx_count() == before
    assert transfer_rows() == 0
    assert_reconciled()


def test_failure_on_the_second_leg_rolls_everything_back(client, monkeypatch):
    a, b = two_accounts(client)
    before = tx_count()
    real = transfer_service._insert_leg
    calls = {"n": 0}

    def explode_on_second(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return real(*args, **kwargs)

    monkeypatch.setattr(transfer_service, "_insert_leg", explode_on_second)

    with SessionLocal() as db:
        with pytest.raises(RuntimeError):
            transfer_service.create_transfer(db, _payload(a, b, "30.00", "T1"))

    assert calls["n"] == 2
    assert balance(client, a) == "100.00" and balance(client, b) == "50.00"
    assert tx_count() == before  # the first leg was rolled back too
    assert transfer_rows() == 0
    assert_reconciled()


# ---------- idempotency ----------
def test_identical_transfer_retry_is_idempotent(client):
    a, b = two_accounts(client)
    first = transfer(client, a, b, "30.00", "T1", "rent")
    again = transfer(client, a, b, "30.00", "T1", "rent")

    assert first.status_code == 201 and again.status_code == 200
    assert again.json()["duplicate"] is True
    assert again.json()["id"] == first.json()["id"]
    assert len(again.json()["transactions"]) == 2
    assert balance(client, a) == "70.00" and balance(client, b) == "80.00"
    assert transfer_rows() == 1
    assert_reconciled()


def test_transfer_retry_with_a_different_payload_conflicts(client):
    a, b = two_accounts(client)
    assert transfer(client, a, b, "30.00", "T1", "rent").status_code == 201

    r = transfer(client, a, b, "31.00", "T1", "rent")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "REFERENCE_ID_CONFLICT"
    assert balance(client, a) == "70.00" and balance(client, b) == "80.00"
    assert transfer_rows() == 1


def test_same_transfer_reference_from_different_sources_is_allowed(client):
    a, b = two_accounts(client)
    c = make_account(client, "C")
    fund(client, c, "10.00")

    assert transfer(client, a, b, "5.00", "SAME").status_code == 201
    assert transfer(client, c, b, "5.00", "SAME").status_code == 201
    assert transfer_rows() == 2
    assert_reconciled()


def test_transfer_retry_is_checked_before_balance(client):
    a, b = two_accounts(client, "100.00", "0.00")
    assert transfer(client, a, b, "100.00", "T1").status_code == 201
    assert balance(client, a) == "0.00"

    # A second application would now be insufficient, but this is a retry.
    again = transfer(client, a, b, "100.00", "T1")
    assert again.status_code == 200
    assert again.json()["duplicate"] is True
    assert balance(client, a) == "0.00" and balance(client, b) == "100.00"


# ---------- concurrency ----------
def test_opposing_concurrent_transfers_do_not_deadlock(client):
    a, b = two_accounts(client, "100.00", "100.00")

    def run(i):
        src, dst = (a, b) if i % 2 == 0 else (b, a)
        with SessionLocal() as db:
            transfer_service.create_transfer(db, _payload(src, dst, "10.00", f"T-{i}"))

    with ThreadPoolExecutor(max_workers=20) as pool:
        for future in [pool.submit(run, i) for i in range(20)]:
            future.result(timeout=60)  # a deadlock would surface as a timeout or DB error

    assert balance(client, a) == "100.00" and balance(client, b) == "100.00"
    assert transfer_rows() == 20
    assert_reconciled()


def test_parallel_transfers_never_overdraw_the_source(client):
    a, b = two_accounts(client, "100.00", "0.00")

    def run(i):
        with SessionLocal() as db:
            try:
                transfer_service.create_transfer(db, _payload(a, b, "10.00", f"T-{i}"))
                return True
            except InsufficientBalance:
                return False

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = [f.result(timeout=60) for f in [pool.submit(run, i) for i in range(20)]]

    assert results.count(True) == 10
    assert balance(client, a) == "0.00" and balance(client, b) == "100.00"
    assert transfer_rows() == 10
    assert_reconciled()
