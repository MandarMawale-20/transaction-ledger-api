from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import DATABASE_URL, DB_MAX_OVERFLOW, DB_POOL_SIZE

engine = create_engine(
    DATABASE_URL,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_pre_ping=True,
)

# expire_on_commit=False so objects returned by services stay readable after
# the service has committed its transaction.
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False, class_=Session
)


def get_db() -> Iterator[Session]:
    """One session per request. Services own the transaction boundary."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
