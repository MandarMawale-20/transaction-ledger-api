import os
from pathlib import Path

from dotenv import load_dotenv

# Reads .env from the project root (not the current working directory) if
# present, so `uvicorn`/`alembic` work when started from another folder.
# Real environment variables win.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://ledger:ledger@localhost:5432/ledger",
)

# Keep the pool comfortably larger than the number of requests you expect to
# hold a row lock at the same time (the concurrency tests fire 20).
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "30"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
