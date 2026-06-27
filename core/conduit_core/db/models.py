from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    pubkey: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lnd_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
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

    __table_args__ = (
        # A virtual agent balance must never go negative — a negative balance means
        # a debit/payment over-spent the ledger (a double-spend or refund bug). The
        # money path already guards this in application code under a row lock; this
        # is the last-line database invariant so even a direct write or a missed
        # check can't quietly strand the ledger below zero. CHECK constraints are
        # always enforced by SQLite (no PRAGMA gates them) and by Postgres; added to
        # already-deployed databases via alembic 0006.
        CheckConstraint("balance_sats >= 0", name="ck_agents_balance_nonneg"),
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    agent: Mapped["Agent"] = relationship("Agent", back_populates="policy")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)  # send|receive
    amount_sats: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_sats: Mapped[int] = mapped_column(BigInteger, default=0)  # LND routing-fee budget/actual
    # Conduit operator's platform fee on this payment (revenue). Separate from
    # fee_sats. Charged on settle, refunded with the rest on failure. See services/fees.py.
    platform_fee_sats: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    destination: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_hash: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    payment_preimage: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payment_request: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    agent: Mapped["Agent"] = relationship("Agent", back_populates="transactions")


class Webhook(Base):
    __tablename__ = "webhooks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    events: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    secret: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TreasuryWithdrawal(Base):
    """Durable record of an operator on-chain withdrawal of accrued funds.

    Written `pending` BEFORE the irreversible broadcast and updated to
    `broadcast` (+txid) after, so a crash in the broadcast window leaves a
    visible, reconcilable record (no silently-spent funds). Also the operator's
    BTC-transfer history.
    """

    __tablename__ = "treasury_withdrawals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    amount_sats: Mapped[int] = mapped_column(BigInteger, nullable=False)
    address: Mapped[str] = mapped_column(String(120), nullable=False)
    sat_per_vbyte: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fee_reserve_sats: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    # pending → broadcast | failed
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    txid: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Idempotency-Key, if the caller supplied one. The withdrawals table IS the
    # idempotency store for this endpoint (a broadcast row dedupes a retry; a
    # failed/absent row is safe to re-attempt — nothing was sent). NULLs are
    # distinct in the unique index, so keyless withdrawals don't collide.
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Solvency snapshot captured right after broadcast (operator audit).
    assets_sats_after: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    liabilities_sats_after: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    __table_args__ = (
        Index("ix_twd_created_at", "created_at"),
        Index("ix_twd_idem_key", "idempotency_key", unique=True),
    )


class IdempotencyRecord(Base):
    """Caches POST responses keyed by the Idempotency-Key (operator-wide).

    The key dedupes across EVERY API key the operator holds — a retry that goes
    out under a different key (rotation, a second worker process) still dedupes
    instead of double-charging. `api_key_id` is retained as an audit column (which
    key first claimed the key), but it is NOT part of the uniqueness scope.

    SECURITY: the same key reused with a different request body is rejected
    with 409 — we never silently return a cached response for a different
    request.

    RETENTION: rows are pruned by created_at once past the retention window
    (IdempotencyPruner). A `pending` reservation (response_status == 0) is written
    BEFORE the payment runs and updated to the real response after; the unique
    index doubles as the concurrency lock that blocks a second in-flight request.
    """

    __tablename__ = "idempotency_responses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    api_key_id: Mapped[str] = mapped_column(
        ForeignKey("api_keys.id"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Unique per `key` alone — operator-wide idempotency. The same key sent
        # under any of the operator's API keys hits this one row, so a cross-key
        # retry dedupes instead of double-charging. (request_hash still rejects a
        # key reused with a different body — see reserve(); 409.)
        Index("ix_idem_key_unique", "key", unique=True),
        # Supports the retention prune (DELETE ... WHERE created_at < cutoff).
        Index("ix_idem_created_at", "created_at"),
    )


class PaymentDecision(Base):
    """Durable, inspectable record of EVERY payment decision — settled, failed,
    AND policy/balance/destination-rejected.

    Unlike `transactions` (which only ever holds rows for payments that PASSED the
    gate), this table records rejected attempts too — the thing a practitioner most
    needs to inspect later — together with the MARGIN to each threshold (how close
    the attempt came to every limit, recorded even when ALLOWED so a near-miss-that-
    passed is visible), the applied policy snapshot+hash (so a later policy edit can
    never make a past decision un-reconstructable; policies aren't versioned), and
    which key/caller initiated it.

    NEVER stores secrets: `api_key_id` (the id, never the key), `destination`
    (public), an opt-in short `caller_tag` (never a prompt), and a policy snapshot
    that carries no secrets. No preimage, seed, or key plaintext is ever written.

    Written best-effort on a SEPARATE session AFTER the money outcome is committed,
    so a decision-record write can never block or alter the money path.
    """

    __tablename__ = "payment_decisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False, index=True)
    # settled | failed | rejected
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # policy CODE (rejected) / failure reason (failed) / null on a clean settle
    reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    requested_sats: Mapped[int] = mapped_column(BigInteger, nullable=False)
    destination: Mapped[str | None] = mapped_column(Text, nullable=True)
    # bolt11 | keysend | address
    destination_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # allowed | no_allowlist | not_allowlisted | blocklisted
    allowlist_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    # The id of the API key that authorized the attempt — NEVER the key plaintext.
    api_key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Opt-in short caller/tool identifier (X-Conduit-Caller). NEVER a prompt dump.
    caller_tag: Mapped[str | None] = mapped_column(String(80), nullable=True)
    balance_at_decision_sats: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # JSON array of per-limit margin entries:
    # {rule, unit, limit, attempted, current, margin_abs, margin_pct, violated}
    thresholds_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # the rule with the tightest (smallest) margin — the headline limit for this decision
    binding_rule: Mapped[str | None] = mapped_column(String(24), nullable=True)
    # tightest margin across thresholds as a % of its limit; null if no quantitative rule
    min_margin_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    # JSON snapshot of the applied policy at decision time + its sha256, so the
    # decision is reconstructable even after the policy is edited in place.
    policy_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # link to the transactions row for ALLOWED payments (null on a rejection)
    tx_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


Index("ix_tx_agent_created", Transaction.agent_id, Transaction.created_at)
Index("ix_tx_agent_status", Transaction.agent_id, Transaction.status)
# Decision-record query paths: per-agent timeline, outcome filter, and the
# "show me the tightest near-misses" sort.
Index("ix_decisions_agent_created", PaymentDecision.agent_id, PaymentDecision.created_at)
Index("ix_decisions_outcome_created", PaymentDecision.outcome, PaymentDecision.created_at)
Index("ix_decisions_min_margin", PaymentDecision.min_margin_pct)
