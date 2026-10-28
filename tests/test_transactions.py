import uuid

import pytest

from tests.helpers import assert_reconciled, balance, fund, make_account, post_tx, tx_count


# ---------- money movement ----------
def test_credit_then_debit_updates_balance(client):
    acc = make_account(client)

    r = post_tx(client, acc, "credit", 100, "C1", "Salary")
    assert r.status_code == 201
    body = r.json()
    assert body["duplicate"] is False
    assert body["account_id"] == acc
    assert body["type"] == "credit"
    assert body["amount"] == "100.00"
    assert body["description"] == "Salary"
    assert body["reference_id"] == "C1"
    assert body["created_at"] and uuid.UUID(body["id"])
    assert balance(client, acc) == "100.00"

    assert post_tx(client, acc, "debit", "30.00", "D1").status_code == 201
    assert balance(client, acc) == "70.00"

    # Spending the exact remaining balance is allowed.
    assert post_tx(client, acc, "debit", "70.00", "D2").status_code == 201
    assert balance(client, acc) == "0.00"
    assert_reconciled()


def test_insufficient_debit_changes_nothing(client):
    acc = make_account(client)
    fund(client, acc, "100.00")

    r = post_tx(client, acc, "debit", "150.00", "D1")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "INSUFFICIENT_BALANCE"
    assert balance(client, acc) == "100.00"
    assert tx_count(acc) == 1  # only the funding credit


@pytest.mark.parametrize("amount", [0, "-1.00", "10.001", "abc", True])
def test_invalid_amounts_are_rejected(client, amount):
    acc = make_account(client)
    r = post_tx(client, acc, "credit", amount, "X")
    assert r.status_code == 422, amount
    assert r.json()["error"]["code"] == "INVALID_AMOUNT"
    assert tx_count(acc) == 0


def test_invalid_type_and_bad_reference_are_rejected(client):
    acc = make_account(client)
    cases = [
        ({"type": "refund", "amount": "10.00", "reference_id": "X"}, "INVALID_TRANSACTION_TYPE"),
        ({"type": "credit", "amount": "10.00"}, "VALIDATION_ERROR"),  # missing reference
        ({"type": "credit", "amount": "10.00", "reference_id": "   "}, "VALIDATION_ERROR"),
        (
            {"type": "credit", "amount": "10.00", "reference_id": "X", "account_id": acc},
            "VALIDATION_ERROR",  # server owns account_id
        ),
    ]
    for payload, code in cases:
        r = client.post(f"/accounts/{acc}/transactions", json=payload)
        assert r.status_code == 422, payload
        assert r.json()["error"]["code"] == code, payload
    assert tx_count(acc) == 0


def test_transaction_for_missing_account_is_404(client):
    r = post_tx(client, uuid.uuid4(), "credit", "10.00", "X")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"


# ---------- idempotency ----------
def test_identical_retry_is_idempotent(client):
    acc = make_account(client)
    first = post_tx(client, acc, "credit", "500.00", "PAY-1", "Salary")
    assert first.status_code == 201

    # Same amount in a different JSON form and a padded reference: still the same request.
    again = post_tx(client, acc, "credit", 500, "  PAY-1 ", "Salary")
    assert again.status_code == 200
    assert again.json()["duplicate"] is True
    assert again.json()["id"] == first.json()["id"]

    assert balance(client, acc) == "500.00"
    assert tx_count(acc) == 1


def test_retry_is_checked_before_balance(client):
    acc = make_account(client)
    fund(client, acc, "100.00")
    assert post_tx(client, acc, "debit", "100.00", "D1").status_code == 201
    assert balance(client, acc) == "0.00"

    # A second application would now be insufficient, but this is a retry of the same debit.
    again = post_tx(client, acc, "debit", "100.00", "D1")
    assert again.status_code == 200
    assert again.json()["duplicate"] is True
    assert balance(client, acc) == "0.00"
    assert tx_count(acc) == 2  # funding + one debit


def test_reference_conflict_on_different_payload(client):
    acc = make_account(client)
    fund(client, acc, "1000.00")
    assert post_tx(client, acc, "credit", "500.00", "PAY-1", "Salary").status_code == 201

    r = post_tx(client, acc, "credit", "500.00", "PAY-1", "Other")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "REFERENCE_ID_CONFLICT"
    assert balance(client, acc) == "1500.00"
    assert tx_count(acc) == 2


def test_same_reference_on_different_accounts_is_allowed(client):
    a, b = make_account(client), make_account(client)
    assert post_tx(client, a, "credit", "10.00", "SHARED").status_code == 201
    assert post_tx(client, b, "credit", "10.00", "SHARED").status_code == 201
    assert balance(client, a) == balance(client, b) == "10.00"


def test_failed_debit_does_not_reserve_its_reference(client):
    acc = make_account(client)
    assert post_tx(client, acc, "debit", "10.00", "D1").status_code == 409

    fund(client, acc, "50.00")
    assert post_tx(client, acc, "debit", "10.00", "D1").status_code == 201
    assert balance(client, acc) == "40.00"


# ---------- integrity ----------
def test_ledger_reconciles_after_mixed_activity(client):
    acc = make_account(client)
    fund(client, acc, "100.00")
    assert post_tx(client, acc, "debit", "30.00", "D1").status_code == 201
    assert post_tx(client, acc, "debit", "500.00", "D2").status_code == 409
    assert post_tx(client, acc, "debit", "30.00", "D1").status_code == 200  # duplicate
    assert post_tx(client, acc, "credit", "0.05", "C1").status_code == 201

    assert balance(client, acc) == "70.05"
    assert tx_count(acc) == 3  # funding, one debit, one credit
    assert_reconciled()
