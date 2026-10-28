"""Deadlock prevention, proven by observing the database rather than trusting the code.

Setup: a "holder" connection locks the LOWER-id account. A transfer from the higher
id to the lower id then has to wait. If the transfer follows the rule (lock the lower
id first), it is blocked on the lower account and holds NOTHING, so a NOWAIT lock on
the higher account succeeds. A transfer that locked in from/to order would already
own the higher account and the NOWAIT probe fails.
"""
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.schemas import TransferCreate
from app.services import transfer_service
from tests.helpers import assert_reconciled, balance, fund, make_account

LOCK = "SELECT 1 FROM accounts WHERE id = CAST(:i AS uuid) FOR UPDATE"


def _waiting_backends() -> int:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                "AND pid <> pg_backend_pid()"
            )
        ).scalar_one()


def test_transfer_locks_the_lower_id_account_first(client):
    a, b = make_account(client, "A"), make_account(client, "B")
    fund(client, a, "100.00")
    fund(client, b, "100.00")
    lo, hi = sorted([a, b], key=lambda s: uuid.UUID(s).int)
    src, dst = hi, lo  # the discriminating direction: from is the higher id

    def run_transfer():
        data = TransferCreate(
            from_account_id=src, to_account_id=dst, amount=Decimal("10.00"), reference_id="T1"
        )
        with SessionLocal() as db:
            transfer_service.create_transfer(db, data)

    holder = engine.connect()
    holder.execute(text(LOCK), {"i": lo})  # transfer must now wait on the lower account
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(run_transfer)
            try:
                deadline = time.time() + 10
                while _waiting_backends() == 0:
                    assert time.time() < deadline, "transfer never blocked on the held lock"
                    time.sleep(0.05)

                probe = engine.connect()
                try:
                    # Raises LockNotAvailable if the blocked transfer already owns the higher account.
                    probe.execute(text(LOCK.replace("FOR UPDATE", "FOR UPDATE NOWAIT")), {"i": hi})
                finally:
                    probe.rollback()
                    probe.close()
            finally:
                # Always release the holder, otherwise a failing probe would leave the
                # transfer thread waiting forever and the test would hang instead of fail.
                holder.rollback()
            future.result(timeout=30)
    finally:
        holder.close()

    assert balance(client, src) == "90.00" and balance(client, dst) == "110.00"
    assert_reconciled()
