from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import accounts, transactions, transfers
from app.core.db import engine
from app.core.errors import register_exception_handlers

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="Transaction Ledger API",
    version="1.0.0",
    description="Accounts, credit/debit transactions with idempotent references, "
    "history, and atomic transfers.",
)
register_exception_handlers(app)

app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(transfers.router)

# The dashboard is three plain files: no build step, no npm, no CDN.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health", tags=["meta"])
def health():
    """Check that the application can reach the database."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}
