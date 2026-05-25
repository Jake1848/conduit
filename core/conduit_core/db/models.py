from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(120), default="")
    key_hash: Mapped[str] = mapped_column(String(120), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), default="read", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    pubkey: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lnd_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    api_key_id: Mapped[str | None] = mapped_column(ForeignKey("api_keys.id"), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Virtual per-agent balance, in sats. The aggregate of all agent balances
    # is bounded above by the LND node's outbound channel capacity. Maintained
    # atomically alongside Transaction inserts inside a row-locked transaction.
    balance_sats: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    policy: Mapped[Optional["Policy"]] = relationship(
        "Policy", back_populates="agent", uselist=False, cascade="all, delete-orphan"
    )
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction", back_populates="agent", cascade="all, delete-orphan"
    )


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id"), nullable=False, unique=True
    )
    max_per_transaction: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_per_hour: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_per_day: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_per_minute_count: Mapped[int] = mapped_column(Integer, default=60)
    allowlist: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    blocklist: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    require_memo: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )

    agent: Mapped["Agent"] = relationship("Agent", back_populates="policy")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)  # send|receive
    amount_sats: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_sats: Mapped[int] = mapped_column(BigInteger, default=0)
    destination: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_hash: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    payment_preimage: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payment_request: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )

    agent: Mapped["Agent"] = relationship("Agent", back_populates="transactions")


class Webhook(Base):
    __tablename__ = "webhooks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    events: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    secret: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


Index("ix_tx_agent_created", Transaction.agent_id, Transaction.created_at)
Index("ix_tx_agent_status", Transaction.agent_id, Transaction.status)
