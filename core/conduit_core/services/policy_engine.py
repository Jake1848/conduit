"""Spending policy enforcement.

CRITICAL: This module gates every outbound payment. It MUST fail closed —
any unexpected error denies the payment.

Rules evaluated in order. The first violation short-circuits with a stable
machine-readable code so SDKs can branch on it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Policy, Transaction

log = structlog.get_logger(__name__)


# ---------- Public types ----------

@dataclass(frozen=True)
class PaymentRequest:
    agent_id: str
    sats: int
    destination: str  # pubkey, ln address, or invoice
    memo: str | None
    dest_pubkey: str | None = None  # parsed/resolved pubkey, if known


@dataclass(frozen=True)
class ThresholdEval:
    """How a single quantitative limit was evaluated for this payment.

    Carries BOTH numbers a margin needs: the `limit`, and what this payment was
    measured against (`current` window usage + this payment's `attempted`
    contribution). `margin_abs = limit - (current + attempted)`; negative means
    this rule was (or would be) violated. Recorded even when the payment is
    ALLOWED — a near-miss that *passed* (tiny positive margin) is the signal a
    practitioner most wants to surface: same 'allowed' verdict, very different risk.
    """

    rule: str          # per_transaction | hourly | daily | rate | balance
    unit: str          # "sats" | "count"
    limit: int
    attempted: int     # this payment's contribution to the window (req.sats, or 1 for rate)
    current: int       # prior usage already in the window (0 for per_transaction / balance)
    margin_abs: int    # limit - (current + attempted); < 0 means violated
    margin_pct: float  # margin_abs / limit * 100 (rounded); < 0 means over the limit
    violated: bool


@dataclass(frozen=True)
class Decision:
    allowed: bool
    code: str
    detail: str
    used_hour_sats: int = 0
    used_day_sats: int = 0
    minute_count: int = 0
    # Per-limit margin breakdown for the inspectable decision record. Populated for
    # every CONFIGURED quantitative rule REACHED: all of them on allow; just
    # per_transaction on a per-tx block; and all window rules (hourly/daily/rate) on
    # a window-rule block, since those are computed together before any is checked.
    # Empty for non-quantitative rejections (disabled / memo / allowlist / blocklist).
    thresholds: tuple[ThresholdEval, ...] = ()


# Stable codes — also documented in docs/reference/errors.md
CODE_OK = "OK"
CODE_POLICY_DISABLED = "POLICY_DISABLED"
CODE_AGENT_INACTIVE = "AGENT_INACTIVE"
CODE_AMOUNT_INVALID = "AMOUNT_INVALID"
CODE_PER_TX_EXCEEDED = "PER_TRANSACTION_LIMIT_EXCEEDED"
CODE_HOURLY_EXCEEDED = "HOURLY_LIMIT_EXCEEDED"
CODE_DAILY_EXCEEDED = "DAILY_LIMIT_EXCEEDED"
CODE_RATE_EXCEEDED = "RATE_LIMIT_EXCEEDED"
CODE_BLOCKLISTED = "DESTINATION_BLOCKLISTED"
CODE_NOT_ALLOWLISTED = "DESTINATION_NOT_ALLOWLISTED"
CODE_MEMO_REQUIRED = "MEMO_REQUIRED"
CODE_EVALUATION_ERROR = "POLICY_EVALUATION_ERROR"


# ---------- Spending window queries ----------

async def _window_sum(
    session: AsyncSession, agent_id: str, since: datetime
) -> tuple[int, int]:
    """Return (sats_total, tx_count) for SETTLED + PENDING outbound payments since `since`."""
    result = await session.execute(
        select(
            func.coalesce(func.sum(Transaction.amount_sats + Transaction.fee_sats), 0),
            func.count(Transaction.id),
        ).where(
            and_(
                Transaction.agent_id == agent_id,
                Transaction.direction == "send",
                Transaction.status.in_(("pending", "settled")),
                Transaction.created_at >= since,
            )
        )
    )
    row = result.first()
    if row is None:
        return 0, 0
    sats, count = row
    return int(sats or 0), int(count or 0)


def _eval_threshold(
    rule: str, unit: str, limit: int | None, current: int, attempted: int
) -> ThresholdEval | None:
    """Build a ThresholdEval, or None if the limit isn't configured (None/0).

    `margin_abs = limit - (current + attempted)`. A near-miss-that-passed has a
    small positive margin; a violation has a negative one.
    """
    if not limit:  # unconfigured rule — nothing to measure against
        return None
    limit = int(limit)
    projected = int(current) + int(attempted)
    margin = limit - projected
    return ThresholdEval(
        rule=rule,
        unit=unit,
        limit=limit,
        attempted=int(attempted),
        current=int(current),
        margin_abs=margin,
        margin_pct=round(margin / limit * 100, 2),
        violated=margin < 0,
    )


# ---------- Engine ----------
#
# Serialization for the same agent is provided by SELECT ... FOR UPDATE on the
# agents row in the calling route (see routes/payments.py). On SQLite that's a
# no-op SQL clause but BEGIN IMMEDIATE provides global write serialization, so
# decisions remain race-free.

class PolicyEngine:
    """Evaluates a payment against an agent's policy.

    A single decision both checks limits AND records a 'pending' Transaction row
    that counts against future windows until it settles or is marked failed.

    Callers MUST call `finalize` with the LND result so that failed payments
    don't keep eating into the agent's window.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def evaluate(self, policy: Policy | None, req: PaymentRequest) -> Decision:
        try:
            return await self._evaluate(policy, req)
        except Exception as e:  # fail closed
            log.exception("policy_evaluation_error", agent_id=req.agent_id, err=str(e))
            return Decision(
                allowed=False,
                code=CODE_EVALUATION_ERROR,
                detail=f"Policy evaluation failed: {e!s}. Payment denied (fail-closed).",
            )

    async def _evaluate(self, policy: Policy | None, req: PaymentRequest) -> Decision:
        if req.sats <= 0:
            return Decision(False, CODE_AMOUNT_INVALID, "Amount must be > 0 sats.")

        # No policy attached → only allow if no limits implied. We treat the
        # absence of a policy as "default allow with rate limit only".
        if policy is None:
            return await self._rate_only(req)

        if not policy.enabled:
            return Decision(
                False,
                CODE_POLICY_DISABLED,
                "Spending policy is disabled (master kill switch).",
            )

        if policy.require_memo and not (req.memo and req.memo.strip()):
            return Decision(False, CODE_MEMO_REQUIRED, "Policy requires a non-empty memo.")

        block = _decode_list(policy.blocklist)
        allow = _decode_list(policy.allowlist)
        if _matches(req, block):
            return Decision(
                False, CODE_BLOCKLISTED, f"Destination is blocklisted: {req.destination}"
            )
        if allow and not _matches(req, allow):
            return Decision(
                False,
                CODE_NOT_ALLOWLISTED,
                f"Destination not in allowlist ({len(allow)} entries): {req.destination}",
            )

        # ----- Quantitative rules → accumulate margin thresholds for the record -----
        # Thresholds are built in evaluation order so a block still carries the
        # binding rule's margin, and ALL configured rules are carried on allow (so a
        # near-miss-that-passed is visible). The allow/deny conditions below are
        # byte-for-byte unchanged — the margin work is purely additive.
        thresholds: list[ThresholdEval] = []
        per_tx = _eval_threshold("per_transaction", "sats", policy.max_per_transaction, 0, req.sats)
        if per_tx:
            thresholds.append(per_tx)
        if policy.max_per_transaction and req.sats > policy.max_per_transaction:
            return Decision(
                False,
                CODE_PER_TX_EXCEEDED,
                f"Payment of {req.sats} sats exceeds per-transaction limit of "
                f"{policy.max_per_transaction} sats.",
                thresholds=tuple(thresholds),
            )

        now = datetime.now(UTC)
        hour_sats, _ = await _window_sum(self.session, req.agent_id, now - timedelta(hours=1))
        day_sats, _ = await _window_sum(self.session, req.agent_id, now - timedelta(days=1))
        _, minute_count = await _window_sum(self.session, req.agent_id, now - timedelta(minutes=1))

        for t in (
            _eval_threshold("hourly", "sats", policy.max_per_hour, hour_sats, req.sats),
            _eval_threshold("daily", "sats", policy.max_per_day, day_sats, req.sats),
            _eval_threshold("rate", "count", policy.max_per_minute_count, minute_count, 1),
        ):
            if t:
                thresholds.append(t)
        common = dict(
            used_hour_sats=hour_sats,
            used_day_sats=day_sats,
            minute_count=minute_count,
            thresholds=tuple(thresholds),
        )

        if policy.max_per_hour and hour_sats + req.sats > policy.max_per_hour:
            return Decision(
                False,
                CODE_HOURLY_EXCEEDED,
                f"Payment of {req.sats} sats would exceed hourly limit of "
                f"{policy.max_per_hour} sats (used: {hour_sats}).",
                **common,
            )
        if policy.max_per_day and day_sats + req.sats > policy.max_per_day:
            return Decision(
                False,
                CODE_DAILY_EXCEEDED,
                f"Payment of {req.sats} sats would exceed daily limit of "
                f"{policy.max_per_day} sats (used: {day_sats}).",
                **common,
            )
        if policy.max_per_minute_count and minute_count + 1 > policy.max_per_minute_count:
            return Decision(
                False,
                CODE_RATE_EXCEEDED,
                f"Would exceed rate limit of {policy.max_per_minute_count} payments/minute "
                f"(current: {minute_count}).",
                **common,
            )

        return Decision(True, CODE_OK, "Allowed", **common)

    async def _rate_only(self, req: PaymentRequest) -> Decision:
        now = datetime.now(UTC)
        _, minute_count = await _window_sum(self.session, req.agent_id, now - timedelta(minutes=1))
        rate = _eval_threshold("rate", "count", 60, minute_count, 1)
        thresholds = (rate,) if rate else ()
        if minute_count + 1 > 60:
            return Decision(
                False,
                CODE_RATE_EXCEEDED,
                "Would exceed default 60 payments/minute rate limit.",
                minute_count=minute_count,
                thresholds=thresholds,
            )
        return Decision(
            True,
            CODE_OK,
            "Allowed (no policy attached; default rate limit only).",
            minute_count=minute_count,
            thresholds=thresholds,
        )


# ---------- helpers ----------

def _decode_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        v = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(v, list):
        return []
    return [str(x).strip().lower() for x in v if str(x).strip()]


def _matches(req: PaymentRequest, entries: Iterable[str]) -> bool:
    targets = {
        (req.destination or "").lower(),
        (req.dest_pubkey or "").lower(),
    }
    targets.discard("")
    for entry in entries:
        if entry in targets:
            return True
    return False


def encode_list(items: list[str] | None) -> str | None:
    if not items:
        return None
    return json.dumps([s.strip() for s in items if s.strip()])
