import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# The app reads DATABASE_URL at import time, so point it at the test DB first.
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://ledger:ledger@localhost:5432/ledger_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

# Tests TRUNCATE every table. Never let that run against a real database.
if "test" not in TEST_DATABASE_URL.rsplit("/", 1)[-1].lower():
    raise RuntimeError(
        f"Refusing to run tests: database name in TEST_DATABASE_URL must contain 'test' ({TEST_DATABASE_URL})"
    )

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.core.db import engine  # noqa: E402
from app.main import app  # noqa: E402


def _ensure_database() -> None:
    url = make_url(TEST_DATABASE_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def _migrated_database():
    _ensure_database()
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")  # tests exercise the real migration
    yield


@pytest.fixture(autouse=True)
def _clean_tables(_migrated_database):
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE transactions, transfers, accounts RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c
