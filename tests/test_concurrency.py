"""Real concurrency against PostgreSQL: every worker uses its own session."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from app.core.db import SessionLocal
from app.core.errors import InsufficientBalance
from app.schemas import TransactionCreate
from app.services import ledger_service
from tests.helpers import assert_reconciled, balance, fund, make_account, tx_count

WORKERS = 20


def _submit(account_id, type_, amount, reference_id):
    from uuid import UUID

    payload = TransactionCreate(type=type_, amount=Decimal(amount), reference_id=reference_id)
    with SessionLocal() as db:
        try:
            _, duplicate = ledger_service.create_transaction(db, UUID(account_id), payload)
            return "duplicate" if duplicate else "created"
        except InsufficientBalance:
            return "insufficient"


def _run(jobs):
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(*job) for job in jobs]
        return [f.result(timeout=60) for f in futures]


def test_parallel_debits_never_overdraw(client):
    acc = make_account(client)
    fund(client, acc, "100.00")

    results = _run([(_submit, acc, "debit", "10.00", f"D-{i}") for i in range(WORKERS)])

    assert results.count("created") == 10
    assert results.count("insufficient") == 10
    assert balance(client, acc) == "0.00"
    assert tx_count(acc) == 11  # funding + 10 debits
    assert_reconciled()


def test_parallel_same_reference_applies_once(client):
    acc = make_account(client)

    results = _run([(_submit, acc, "credit", "25.00", "SAME-REF") for _ in range(WORKERS)])

    assert results.count("created") == 1
    assert results.count("duplicate") == WORKERS - 1
    assert balance(client, acc) == "25.00"
    assert tx_count(acc) == 1
    assert_reconciled()
