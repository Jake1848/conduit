from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

Direction = Literal["send", "receive"]
TxStatus = Literal["pending", "settled", "failed"]
Scope = Literal["read", "write", "admin"]

# Total bitcoin supply in sats (21M BTC). A sane upper bound for any sats field —
# rejects bigint-overflow inputs (which would otherwise 500 in Postgres) with a
# clean 422 instead.
MAX_SATS = 2_100_000_000_000_000


def _no_null_bytes(v: str) -> str:
    # Postgres text columns reject NUL (0x00); validate here so the API returns a
    # clean 422 instead of a 500 from asyncpg on insert.
    if "\x00" in v:
        raise ValueError("must not contain null bytes")
    return v


# A `str` that additionally rejects embedded null bytes.
SafeStr = Annotated[str, AfterValidator(_no_null_bytes)]


def _valid_pubkey(v: str) -> str:
    # A compressed secp256k1 node pubkey: exactly 66 hex chars, 02/03 prefix.
    # Validate at the EDGE so a malformed pubkey returns 422 BEFORE any debit —
    # otherwise keysend's bytes.fromhex() would raise mid-payment, AFTER the
    # agent was debited, stranding funds in needs_reconciliation for a payment
    # that never left the node.
    s = v.strip()
    if len(s) != 66 or s[:2] not in ("02", "03"):
        raise ValueError("dest_pubkey must be a 66-char compressed pubkey (02/03 prefix)")
    try:
        bytes.fromhex(s)
    except ValueError as e:
        raise ValueError("dest_pubkey must be valid hex") from e
    return s


# An optional compressed node pubkey (validated when present).
Pubkey = Annotated[str, AfterValidator(_valid_pubkey)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Agents ----------

class AgentCreate(BaseModel):
    name: SafeStr = Field(..., min_length=1, max_length=120)
    daily_limit: int | None = Field(
        None, ge=1, le=MAX_SATS, description="Convenience: sets policy.max_per_day"
    )
    metadata: dict[str, Any] | None = None


class AgentOut(ORM):
    id: str
    name: str
    pubkey: str | None = None
    active: bool
    created_at: datetime
    # Denormalized spendable balance (already on the Agent row). Additive: lets the
    # dashboard sum a fleet treasury + show balances without N per-agent /balance calls.
    balance_sats: int = 0


class AgentListOut(BaseModel):
    data: list[AgentOut]
    # True when the page filled the limit — there may be more agents to fetch
    # (offset += limit). Lets a client page the whole fleet instead of silently
    # truncating at the default page size.
    has_more: bool = False


class BalanceOut(BaseModel):
    agent_id: str
    available_sats: int
    pending_sats: int
    total_sats: int


class LedgerAdjustIn(BaseModel):
    sats: int = Field(..., ge=1, le=MAX_SATS, description="Amount to credit (or debit) in sats")
    reason: SafeStr = Field("", max_length=200)
    metadata: dict[str, Any] | None = None


class LedgerAdjustOut(BaseModel):
    agent_id: str
    transaction_id: str
    delta_sats: int  # positive = credit, negative = debit
    balance_sats: int


# ---------- Policies ----------

class PolicyIn(BaseModel):
    max_per_transaction: int | None = Field(None, ge=1, le=MAX_SATS)
    max_per_hour: int | None = Field(None, ge=1, le=MAX_SATS)
    max_per_day: int | None = Field(None, ge=1, le=MAX_SATS)
    max_per_minute_count: int | None = Field(60, ge=1, le=10_000)
    # Bounded (audit L8): each is a list of ≤66-hex Lightning pubkeys; cap the
    # count and item length so a policy can't store an unbounded blob.
    allowlist: list[Annotated[str, Field(max_length=140)]] | None = Field(None, max_length=1000)
    blocklist: list[Annotated[str, Field(max_length=140)]] | None = Field(None, max_length=1000)
    require_memo: bool = False
    enabled: bool = True


class PolicyOut(BaseModel):
    id: str
    agent_id: str
    max_per_transaction: int | None
    max_per_hour: int | None
    max_per_day: int | None
    max_per_minute_count: int
    allowlist: list[str]
    blocklist: list[str]
    require_memo: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime | None


# ---------- Payments / Invoices ----------

class PaymentSendIn(BaseModel):
    """Pay a BOLT11 invoice or do keysend to a pubkey."""
    agent_id: str
    payment_request: str | None = Field(None, max_length=4000, description="BOLT11 invoice string")
    dest_pubkey: Pubkey | None = Field(None, max_length=140, description="For keysend")
    sats: int | None = Field(
        None, ge=1, le=MAX_SATS, description="Required for keysend or zero-amount invoices"
    )
    memo: SafeStr | None = Field(None, max_length=500)  # bounded (L7)
    metadata: dict[str, Any] | None = None


class PaymentPayIn(BaseModel):
    """Pay a Conduit/Lightning Address: name@host or ln address."""
    agent_id: str
    to: str = Field(
        ..., max_length=2000, description="Lightning address (name@host) or BOLT11 invoice"
    )
    sats: int = Field(..., ge=1, le=MAX_SATS)
    memo: SafeStr | None = Field(None, max_length=500)  # bounded (L7)
    metadata: dict[str, Any] | None = None


class ReceiptOut(BaseModel):
    id: str
    agent_id: str
    status: TxStatus
    hash: str | None = Field(None, description="Payment hash (hex)")
    amount_sats: int
    fee_sats: int = Field(0, description="LND routing fee (budget while pending, actual on settle)")
    platform_fee_sats: int = Field(0, description="Conduit operator platform fee (revenue)")
    settled_in_ms: int | None = None
    destination: str | None = None
    memo: str | None = None
    created_at: datetime


class InvoiceCreateIn(BaseModel):
    agent_id: str
    amount: int = Field(..., ge=1, le=MAX_SATS, description="Sats")
    memo: SafeStr | None = None
    expiry: int = Field(3600, ge=60, le=7 * 24 * 3600)


class InvoiceOut(BaseModel):
    id: str
    agent_id: str
    payment_request: str
    payment_hash: str
    amount_sats: int
    memo: str | None
    status: TxStatus
    expires_at: datetime
    created_at: datetime


# ---------- Transactions ----------

class TransactionOut(BaseModel):
    id: str
    agent_id: str
    direction: Direction
    amount_sats: int
    fee_sats: int
    platform_fee_sats: int = Field(0, description="Conduit operator platform fee (revenue)")
    destination: str | None
    payment_hash: str | None
    status: TxStatus
    memo: str | None
    settled_at: datetime | None
    latency_ms: int | None
    created_at: datetime


class TransactionListOut(BaseModel):
    data: list[TransactionOut]
    has_more: bool = False


# ---------- Webhooks ----------

class WebhookIn(BaseModel):
    url: SafeStr = Field(..., max_length=2000)  # SafeStr rejects null bytes (→422 not 500)
    events: list[str] = Field(default_factory=lambda: ["payment.settled", "payment.failed"])


class WebhookOut(BaseModel):
    id: str
    url: str
    events: list[str]
    secret: str | None = Field(None, description="Returned only at creation time")
    active: bool
    created_at: datetime


# ---------- System ----------

class StatusOut(BaseModel):
    env: str
    network: str
    node: dict[str, Any]
    balance: dict[str, Any]
    channels: dict[str, Any]


class HealthOut(BaseModel):
    ok: bool = True
    version: str
    network: str


class ComponentHealth(BaseModel):
    ok: bool
    detail: str | None = None


class ReadyOut(BaseModel):
    """Readiness probe payload. `ok` reflects whether the API can serve money-path
    traffic — the database is a HARD dependency; LND degradation is surfaced but
    not treated as fatal (it shouldn't restart-loop the API while the node resyncs)."""

    ok: bool
    version: str
    network: str
    components: dict[str, ComponentHealth]


# ---------- API keys ----------

class APIKeyCreateIn(BaseModel):
    scope: Scope = "read"
    label: SafeStr = Field("", max_length=120)


class APIKeyOut(BaseModel):
    id: str
    label: str
    scope: Scope
    secret: str | None = Field(None, description="Shown exactly once at creation")
    created_at: datetime


class APIKeyListItem(BaseModel):
    id: str
    label: str
    scope: Scope
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked: bool


class APIKeyListOut(BaseModel):
    data: list[APIKeyListItem]


# ---------- Fleet metrics (dashboard) ----------

class HourBucket(BaseModel):
    hour: datetime          # UTC hour-start
    count: int              # transactions in that hour
    volume_sats: int        # summed amount_sats in that hour


class TopAgentOut(BaseModel):
    agent_id: str
    name: str
    tx_today: int
    balance_sats: int
    active: bool


class MetricsOut(BaseModel):
    treasury_sats: int
    active_agents: int
    total_agents: int
    tx_per_min: int
    avg_settlement_ms: int | None
    p99_settlement_ms: int | None
    hourly: list[HourBucket]      # 24 buckets, oldest → newest
    top_agents: list[TopAgentOut]  # most active today
    fee_revenue_total_sats: int = 0   # platform fees collected, all-time
    fee_revenue_today_sats: int = 0   # platform fees collected since 00:00 UTC
    # ---- solvency (latest monitor snapshot) ----
    # Σ agent balances + pending outbound — what the operator's node must back.
    liabilities_sats: int = 0
    # Channel-local + confirmed on-chain liquidity backing the ledger.
    assets_sats: int = 0
    # assets / liabilities. None when there are no liabilities (undefined ratio)
    # or when no snapshot exists yet (monitor hasn't run its first pass).
    solvency_ratio: float | None = None
    # True when the ledger is currently backed (assets >= liabilities). Defaults
    # True (no claims to back) until the first snapshot lands.
    solvent: bool = True


# ---------- Platform fees (operator revenue) ----------

class FeeDayBucket(BaseModel):
    date: str          # YYYY-MM-DD (UTC)
    sats: int
    tx_count: int


class FeesOut(BaseModel):
    total_collected_sats: int
    total_collected_btc: float
    today_sats: int
    fees_by_day: list[FeeDayBucket]  # most recent first


# ---------- Treasury (owner/admin) ----------

class WithdrawalItem(ORM):
    """One on-chain withdrawal of accrued funds (BTC-transfer history)."""

    id: str
    amount_sats: int
    address: str
    status: str  # pending | broadcast | failed
    txid: str | None = None
    error: str | None = None
    created_at: datetime


class TreasuryOverviewOut(BaseModel):
    """Owner view: accrued revenue + node liquidity + solvency + how much of the
    on-chain balance can be withdrawn without breaching solvency."""

    # Revenue — accounting figure (Σ settled platform_fee_sats), NOT a segregated
    # wallet. The sats live in the operator's own node, commingled with liquidity.
    revenue_total_sats: int
    revenue_total_btc: float
    revenue_today_sats: int
    revenue_by_day: list[FeeDayBucket]

    # Node liquidity (assets backing agent balances).
    onchain_confirmed_sats: int
    channel_local_sats: int
    assets_sats: int

    # Liabilities the assets must cover, and the resulting solvency.
    agent_liabilities_sats: int
    solvent: bool
    solvency_ratio: float | None

    # Max sats withdrawable on-chain right now without dropping assets below
    # liabilities (bounded by the on-chain confirmed balance minus a fee reserve).
    # Assumes the DEFAULT fee rate; a higher sat_per_vbyte enlarges the reserve, so
    # the actual withdraw guard may allow slightly less. fee_reserve_sats is the
    # default-rate reserve this figure used.
    withdrawable_sats: int
    fee_reserve_sats: int
    # Most-recent on-chain withdrawals (BTC-transfer history).
    recent_withdrawals: list[WithdrawalItem] = []
    # Set if the LND balance couldn't be read (figures are partial / conservative).
    error: str | None = None


class WithdrawIn(BaseModel):
    amount_sats: int = Field(..., ge=1, le=MAX_SATS, description="On-chain amount to send")
    address: SafeStr = Field(
        ..., min_length=10, max_length=120, description="Destination on-chain address"
    )
    sat_per_vbyte: int | None = Field(
        None, ge=1, le=10_000, description="Optional fee rate; LND estimates if omitted"
    )


class WithdrawOut(BaseModel):
    withdrawal_id: str
    txid: str
    amount_sats: int
    address: str
    status: str
    # Solvency AFTER the withdrawal (recomputed for the operator's confirmation).
    # None if LND was unreadable right after the broadcast — the send still
    # succeeded (txid is set); these are display-only.
    assets_sats: int | None = None
    agent_liabilities_sats: int | None = None
    withdrawable_sats_remaining: int | None = None
