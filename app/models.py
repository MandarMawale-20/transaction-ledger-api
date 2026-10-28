"""ORM models.

The database schema (including every constraint and index) is owned by the
Alembic migration in migrations/versions/0001_initial.py. These models only
describe columns so the services can read and write them.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Numeric, Text, Uuid, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


_NOW = text("clock_timestamp()")


class Account(Base):
    __tablename__ = "accounts"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_NOW
    )


class Transfer(Base):
    __tablename__ = "transfers"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    from_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id"), nullable=False
    )
    to_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    reference_id: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_NOW
    )


class Transaction(Base):
    __tablename__ = "transactions"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Ledger-write ordering for history (see docs/ARCHITECTURE.md section 10).
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    reference_id: Mapped[str] = mapped_column(Text, nullable=False)
    transfer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("transfers.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_NOW
    )
