"""Inspectable payment Decision Record — durable capture of every payment decision.

For EVERY attempt (settled / failed / rejected) we persist a queryable record
carrying the MARGIN to each threshold (how close it came to each limit — recorded
even when ALLOWED, because a near-miss-that-passed is the most important thing to
surface), the applied policy snapshot + hash (so a later policy edit can't make a
past decision un-reconstructable; policies aren't versioned), and which key/caller
initiated it.

HARD GUARANTEES:
  * The write runs on a SEPARATE session, AFTER the money outcome is committed, and
    NEVER raises into the money path — an audit-write failure is logged + metered
    but the payment outcome is unaffected.
  * NEVER stores secrets: api_key_id is an id (never the key), caller_tag is a short
    opt-in tag (never a prompt), the policy snapshot carries no secrets, and no
    preimage / seed / key plaintext is ever written.

See db.models.PaymentDecision and routes/payments.py for the capture points.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog

from ..db.models import PaymentDecision, Policy
from ..observability import record_decision_write_failure
from .ids import decision_id
from .policy_engine import CODE_BLOCKLISTED, CODE_NOT_ALLOWLISTED, Decision, ThresholdEval

log = structlog.get_logger(__name__)

OUTCOME_SETTLED = "settled"
OUTCOME_FAILED = "failed"
OUTCOME_REJECTED = "rejected"

_CALLER_TAG_MAX = 80
_REASON_MAX = 80


@dataclass
class DecisionSnapshot:
    """Everything captured AT decision time, before the money outcome is known.

    Built once in the money path (after policy evaluation, before the debit); the
    terminal outcome + tx link are supplied when the record is written. Holds NO
    secret.
    """

    agent_id: str
    requested_sats: int
    destination: str | None
    destination_kind: str | None
    allowlist_status: str | None
    api_key_id: str | None
    caller_tag: str | None
    balance_at_decision_sats: int | None
    thresholds: tuple[ThresholdEval, ...] = ()
    policy_snapshot: dict | None = None
    policy_hash: str | None = None


def _safe_list(raw: str | None) -> list:
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def snapshot_policy(policy: Policy | None) -> tuple[dict | None, str]:
    """Canonical JSON snapshot of the applied policy + its sha256.

    Reconstructable even after the policy is edited in place. A None policy hashes
    stably too, so a 'no-policy' decision is still distinguishable.
    """
    snap = (
        None
        if policy is None
        else {
            "max_per_transaction": policy.max_per_transaction,
            "max_per_hour": policy.max_per_hour,
            "max_per_day": policy.max_per_day,
            "max_per_minute_count": policy.max_per_minute_count,
            "allowlist": _safe_list(policy.allowlist),
            "blocklist": _safe_list(policy.blocklist),
            "require_memo": bool(policy.require_memo),
            "enabled": bool(policy.enabled),
        }
    )
    canonical = json.dumps(snap, sort_keys=True, separators=(",", ":"))
    return snap, hashlib.sha256(canonical.encode()).hexdigest()


def allowlist_status_for(policy: Policy | None, decision: Decision) -> str:
    """Where this destination stood against the allow/blocklist."""
    if decision.code == CODE_BLOCKLISTED:
        return "blocklisted"
    if decision.code == CODE_NOT_ALLOWLISTED:
        return "not_allowlisted"
    if policy is not None and _safe_list(policy.allowlist):
        return "allowed"
    return "no_allowlist"


def balance_threshold(balance_sats: int, required_sats: int) -> ThresholdEval:
    """The balance as a margin: limit = available balance, attempted = required debit.

    A negative margin means the debit exceeds the balance (the InsufficientBalance
    rejection). Captured so a 'rejected for funds' decision shows by how much.
    """
    balance_sats = int(balance_sats)
    required_sats = int(required_sats)
    margin = balance_sats - required_sats
    if balance_sats > 0:
        pct = round(margin / balance_sats * 100, 2)
    else:
        pct = 0.0 if required_sats == 0 else -100.0
    return ThresholdEval(
        rule="balance",
        unit="sats",
        limit=balance_sats,
        attempted=required_sats,
        current=0,
        margin_abs=margin,
        margin_pct=pct,
        violated=margin < 0,
    )


def _binding(thresholds: tuple[ThresholdEval, ...]) -> tuple[str | None, float | None]:
    """The rule with the tightest margin (the headline limit) + its margin %.

    Smallest margin_pct wins — violations (negative) sort first, otherwise the
    smallest positive margin (the closest near-miss)."""
    if not thresholds:
        return None, None
    tightest = min(thresholds, key=lambda t: t.margin_pct)
    return tightest.rule, tightest.margin_pct


def _thresholds_json(thresholds: tuple[ThresholdEval, ...]) -> str | None:
    if not thresholds:
        return None
    return json.dumps(
        [
            {
                "rule": t.rule,
                "unit": t.unit,
                "limit": t.limit,
                "attempted": t.attempted,
                "current": t.current,
                "margin_abs": t.margin_abs,
                "margin_pct": t.margin_pct,
                "violated": t.violated,
            }
            for t in thresholds
        ],
        separators=(",", ":"),
    )


async def record_decision(
    snapshot: DecisionSnapshot,
    outcome: str,
    *,
    reason_code: str | None = None,
    tx_id: str | None = None,
) -> str | None:
    """Persist a Decision Record on a SEPARATE session, best-effort.

    NEVER raises and NEVER touches the caller's money-path session. Returns True on
    success, else None (failure logged + metered)."""
    from ..db import SessionLocal  # local import avoids an import cycle

    binding_rule, min_margin_pct = _binding(snapshot.thresholds)
    try:
        async with SessionLocal() as fresh:
            fresh.add(
                PaymentDecision(
                    id=decision_id(),
                    agent_id=snapshot.agent_id,
                    outcome=outcome,
                    reason_code=(reason_code[:_REASON_MAX] if reason_code else None),
                    requested_sats=int(snapshot.requested_sats),
                    destination=snapshot.destination,
                    destination_kind=snapshot.destination_kind,
                    allowlist_status=snapshot.allowlist_status,
                    api_key_id=snapshot.api_key_id,
                    caller_tag=(
                        snapshot.caller_tag[:_CALLER_TAG_MAX]
                        if snapshot.caller_tag
                        else None
                    ),
                    balance_at_decision_sats=snapshot.balance_at_decision_sats,
                    thresholds_json=_thresholds_json(snapshot.thresholds),
                    binding_rule=binding_rule,
                    min_margin_pct=min_margin_pct,
                    policy_snapshot_json=(
                        json.dumps(snapshot.policy_snapshot, separators=(",", ":"))
                        if snapshot.policy_snapshot is not None
                        else None
                    ),
                    policy_hash=snapshot.policy_hash,
                    tx_id=tx_id,
                    # Stamp with microsecond Python time (not the DB's second-
                    # resolution server_default) so the decision log is reliably
                    # orderable even for many attempts within the same second.
                    created_at=datetime.now(UTC),
                )
            )
            await fresh.commit()
            return True  # noqa: TRY300 — id not needed by callers; presence == success
    except Exception as e:  # noqa: BLE001 — audit must NEVER break the money path
        log.error(
            "decision_record_write_failed",
            agent_id=snapshot.agent_id,
            outcome=outcome,
            err=str(e),
        )
        record_decision_write_failure()
        return None
