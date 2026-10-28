# Transaction Ledger API

A small FastAPI and PostgreSQL service for accounts and money movement. It supports account creation,
credits, debits, balances, filtered transaction history, and atomic transfers. Writes are idempotent through
a caller-supplied `reference_id`, so retrying a request cannot apply it twice.

## Features

- Create, list, and fetch accounts. New accounts always start at `0.00`.
- Post credits and debits with strict decimal validation.
- Idempotent writes: the caller supplies a unique `reference_id` for each logical operation and reuses it
  when retrying. Identical retries return the original result; a changed payload returns `409`.
- Read a balance or paginated transaction history, optionally filtered by `credit` / `debit`.
- Move money between accounts atomically. Transfers lock both accounts in ascending UUID order.
- Exact money: PostgreSQL uses `NUMERIC(18,2)`, Python uses `Decimal`, and JSON returns two-decimal strings.
  Over-precise amounts are rejected rather than rounded.
- History is ordered by the identity-based `seq` column, which follows ledger write order.
- Uniform JSON error envelope with specific error codes, backed by database constraints.
- Plain HTML/CSS/JavaScript dashboard served by the same application, with no build step.

![Dashboard](docs/dashboard.png)

## Architecture

```mermaid
flowchart TD
    Browser[Browser dashboard] --> API[FastAPI routes + Pydantic]
    Client[HTTP client] --> API
    API --> Service[Service layer]
    Service --> ORM[SQLAlchemy models]
    ORM --> DB[(PostgreSQL)]
    Migrations[Alembic migrations] --> DB
```

Routes handle HTTP concerns and request validation. Services enforce business rules and manage database
transactions. PostgreSQL constraints provide a final layer of integrity protection. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for concurrency and idempotency details.

## Tech stack

- Python 3.11+ (developed on 3.12)
- FastAPI, Pydantic v2
- SQLAlchemy 2.x, psycopg 3
- PostgreSQL 14+, Alembic
- pytest and httpx

## Prerequisites

- Python 3.11 or newer
- A running PostgreSQL 14+ server
- `psql` on `PATH`

## Setup and run

1. Create the local development role and databases. The script creates the `ledger` role plus `ledger` and
   `ledger_test` databases, and is safe to re-run. If you already have a configured PostgreSQL instance,
   you can create equivalent role and databases manually and set `DATABASE_URL` and `TEST_DATABASE_URL`.

   ```bash
   psql -U postgres -f scripts/setup_db.sql
   ```

   Use your PostgreSQL superuser if it is not `postgres`. On Linux this is often
   `sudo -u postgres psql -f scripts/setup_db.sql`.

2. Create a virtual environment, install dependencies, and create `.env`.

   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   cp .env.example .env             # Windows: copy .env.example .env
   ```

3. Apply the database migration.

   ```bash
   alembic upgrade head
   ```

4. Start the API from the repository root.

   ```bash
   uvicorn app.main:app --reload
   ```

5. Open:

   - Dashboard: <http://localhost:8000/>
   - Swagger UI: <http://localhost:8000/docs>
   - Health check: <http://localhost:8000/health>

## Environment variables

`.env` is loaded from the repository root. Real environment variables take precedence.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://ledger:ledger@localhost:5432/ledger` | Application database |
| `TEST_DATABASE_URL` | `postgresql+psycopg://ledger:ledger@localhost:5432/ledger_test` | Test database; its name must contain `test` |
| `DB_POOL_SIZE` | `30` | SQLAlchemy connection pool size |
| `DB_MAX_OVERFLOW` | `20` | Additional pooled connections |

## API example

Create an account:

```bash
curl -X POST localhost:8000/accounts \
  -H 'Content-Type: application/json' \
  -d '{"name": "Asha Rao"}'
```

Use the returned account id to post a transaction:

```bash
curl -X POST localhost:8000/accounts/$ACCOUNT_ID/transactions \
  -H 'Content-Type: application/json' \
  -d '{"type": "credit", "amount": "150.00", "reference_id": "PAY-001", "description": "Salary"}'
```

## Running tests

```bash
pytest
```

The suite runs against PostgreSQL, because the concurrency tests depend on real row locks. It applies the
Alembic migration to `TEST_DATABASE_URL` and truncates its tables between tests. It refuses to run unless the
database name contains `test`.

## Documentation

- Full request/response reference and error catalogue: [`docs/API.md`](docs/API.md)
- Architecture and design details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Assumptions and scope: [`ASSUMPTIONS.md`](ASSUMPTIONS.md)
- OpenAPI JSON: [`docs/openapi.json`](docs/openapi.json), also served at `/openapi.json`

## Scope and limitations

Single currency, no authentication, and no account deletion; corrections are new transactions. Offset
pagination can shift during concurrent inserts, and `total` / `items` are separate queries. See
[`ASSUMPTIONS.md`](ASSUMPTIONS.md) for the complete scope.
