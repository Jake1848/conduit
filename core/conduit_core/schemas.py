from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Direction = Literal["send", "receive"]
TxStatus = Literal["pending", "settled", "failed"]
Scope = Literal["read", "write", "admin"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Agents ----------

class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    daily_limit: int | None = Field(None, ge=1, description="Convenience: sets policy.max_per_day")
    metadata: dict[str, Any] | None = None


class AgentOut(ORM):
    id: str
    name: str
    pubkey: str | None = None
    active: bool
    created_at: datetime


class AgentListOut(BaseModel):
    data: list[AgentOut]


class BalanceOut(BaseModel):
    agent_id: str
    available_sats: int
    pending_sats: int
    total_sats: int


# ---------- Policies ----------

class PolicyIn(BaseModel):
    max_per_transaction: int | None = Field(None, ge=1)
    max_per_hour: int | None = Field(None, ge=1)
    max_per_day: int | None = Field(None, ge=1)
    max_per_minute_count: int | None = Field(60, ge=1, le=10_000)
    allowlist: list[str] | None = None
    blocklist: list[str] | None = None
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
    payment_request: str | None = Field(None, description="BOLT11 invoice string")
    dest_pubkey: str | None = Field(None, description="For keysend")
    sats: int | None = Field(None, ge=1, description="Required for keysend or zero-amount invoices")
    memo: str | None = None
    metadata: dict[str, Any] | None = None


class PaymentPayIn(BaseModel):
    """Pay a Conduit/Lightning Address: name@host or ln address."""
    agent_id: str
    to: str = Field(..., description="Lightning address (name@host) or BOLT11 invoice")
    sats: int = Field(..., ge=1)
    memo: str | None = None
    metadata: dict[str, Any] | None = None


class ReceiptOut(BaseModel):
    id: str
    agent_id: str
    status: TxStatus
    hash: str | None = Field(None, description="Payment hash (hex)")
    amount_sats: int
    fee_sats: int
    settled_in_ms: int | None = None
    destination: str | None = None
    memo: str | None = None
    created_at: datetime


class InvoiceCreateIn(BaseModel):
    agent_id: str
    amount: int = Field(..., ge=1, description="Sats")
    memo: str | None = None
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
    url: str
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


# ---------- API keys ----------

class APIKeyCreateIn(BaseModel):
    scope: Scope = "read"
    label: str = ""


class APIKeyOut(BaseModel):
    id: str
    label: str
    scope: Scope
    secret: Optional[str] = Field(None, description="Shown exactly once at creation")
    created_at: datetime
