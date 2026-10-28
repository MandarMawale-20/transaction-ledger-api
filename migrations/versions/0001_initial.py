"""initial schema: accounts, transfers, transactions

Revision ID: 0001
Revises:
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Created in dependency order: accounts -> transfers -> transactions.
    op.execute(
        """
        CREATE TABLE accounts (
            id          UUID PRIMARY KEY,
            name        TEXT NOT NULL,
            balance     NUMERIC(18,2) NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT ck_accounts_name_not_blank CHECK (length(trim(name)) > 0),
            CONSTRAINT ck_accounts_balance_non_negative CHECK (balance >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE transfers (
            id               UUID PRIMARY KEY,
            from_account_id  UUID NOT NULL REFERENCES accounts(id),
            to_account_id    UUID NOT NULL REFERENCES accounts(id),
            amount           NUMERIC(18,2) NOT NULL,
            reference_id     TEXT NOT NULL,
            description      TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT ck_transfers_amount_positive CHECK (amount > 0),
            CONSTRAINT ck_transfers_reference_not_blank CHECK (length(trim(reference_id)) > 0),
            CONSTRAINT ck_transfers_accounts_distinct CHECK (from_account_id <> to_account_id),
            CONSTRAINT uq_transfers_from_reference UNIQUE (from_account_id, reference_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE transactions (
            id            UUID PRIMARY KEY,
            seq           BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
            account_id    UUID NOT NULL REFERENCES accounts(id),
            type          TEXT NOT NULL,
            amount        NUMERIC(18,2) NOT NULL,
            description   TEXT,
            reference_id  TEXT NOT NULL,
            transfer_id   UUID REFERENCES transfers(id),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT uq_transactions_seq UNIQUE (seq),
            CONSTRAINT ck_transactions_type CHECK (type IN ('credit', 'debit')),
            CONSTRAINT ck_transactions_amount_positive CHECK (amount > 0),
            CONSTRAINT ck_transactions_reference_not_blank CHECK (length(trim(reference_id)) > 0),
            CONSTRAINT uq_transactions_account_reference UNIQUE (account_id, reference_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_transactions_account_seq ON transactions (account_id, seq DESC)"
    )
    op.execute(
        "CREATE INDEX idx_transactions_transfer ON transactions (transfer_id) "
        "WHERE transfer_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS transactions")
    op.execute("DROP TABLE IF EXISTS transfers")
    op.execute("DROP TABLE IF EXISTS accounts")
