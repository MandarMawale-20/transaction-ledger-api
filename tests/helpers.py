from sqlalchemy import text

from app.core.db import engine


def make_account(client, name="Test User") -> str:
    r = client.post("/accounts", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def post_tx(client, account_id, type_, amount, reference_id, description=None):
    body = {"type": type_, "amount": amount, "reference_id": reference_id}
    if description is not None:
        body["description"] = description
    return client.post(f"/accounts/{account_id}/transactions", json=body)


def fund(client, account_id, amount, reference_id="FUND"):
    r = post_tx(client, account_id, "credit", amount, reference_id)
    assert r.status_code == 201, r.text
    return r


def balance(client, account_id) -> str:
    r = client.get(f"/accounts/{account_id}/balance")
    assert r.status_code == 200, r.text
    return r.json()["balance"]


def tx_count(account_id=None) -> int:
    sql = "SELECT count(*) FROM transactions"
    params = {}
    if account_id:
        sql += " WHERE account_id = :a"
        params = {"a": account_id}
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def assert_reconciled() -> None:
    """Every stored balance must equal credits - debits from the ledger."""
    sql = """
        SELECT a.id, a.balance,
               COALESCE(SUM(CASE WHEN t.type = 'credit' THEN t.amount ELSE -t.amount END), 0) AS ledger
        FROM accounts a LEFT JOIN transactions t ON t.account_id = a.id
        GROUP BY a.id, a.balance
    """
    with engine.connect() as conn:
        for row in conn.execute(text(sql)):
            assert row.balance == row.ledger, f"account {row.id}: balance {row.balance} != ledger {row.ledger}"
