from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .payment import _parse_dt


@dataclass(frozen=True)
class Threshold:
    """How one quantitative limit was evaluated for a payment — the margin data.

    `margin_abs = limit - (current + attempted)`; a negative margin means the
    rule was violated. Present even on an ALLOWED decision (a near-miss that
    passed), so you can alert before a limit is actually hit.
    """

    rule: str  # 'per_transaction' | 'hourly' | 'daily' | 'rate' | 'balance'
    unit: str  # 'sats' | 'count'
    limit: int
    attempted: int  # this payment's contribution to the window
    current: int  # prior usage already in the window
    margin_abs: int  # limit - (current + attempted); < 0 means violated
    margin_pct: float  # margin as a percent of the limit; < 0 means over
    violated: bool

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Threshold":
        return cls(
            rule=data["rule"],
            unit=data["unit"],
            limit=int(data["limit"]),
            attempted=int(data["attempted"]),
            current=int(data["current"]),
            margin_abs=int(data["margin_abs"]),
            margin_pct=float(data["margin_pct"]),
            violated=bool(data["violated"]),
        )


@dataclass(frozen=True)
class Decision:
    """A durable, inspectable record of one payment decision — settled, failed,
    OR policy/balance/destination-rejected — with the margin to each threshold,
    the applied-policy snapshot, and who initiated it. No secret is ever included.

        for d in agent.decisions(outcome="rejected"):
            print(d.outcome, d.binding_rule, d.min_margin_pct)
    """

    id: str
    agent_id: str
    outcome: str  # 'settled' | 'failed' | 'rejected'
    reason_code: str | None
    requested_sats: int
    destination: str | None
    destination_kind: str | None  # 'bolt11' | 'keysend' | 'address' | None
    allowlist_status: str | None  # 'allowed' | 'no_allowlist' | 'not_allowlisted' | 'blocklisted'
    api_key_id: str | None  # id of the authorizing key — never the secret
    caller_tag: str | None
    balance_at_decision_sats: int | None
    thresholds: list[Threshold]  # per-limit margin breakdown — present even when ALLOWED
    binding_rule: str | None  # the rule with the tightest margin
    min_margin_pct: float | None  # tightest margin across thresholds (% of its limit)
    policy_snapshot: dict[str, Any] | None  # applied policy at decision time
    policy_hash: str | None
    tx_id: str | None  # linked transaction for allowed payments
    created_at: datetime

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Decision":
        return cls(
            id=data["id"],
            agent_id=data["agent_id"],
            outcome=data["outcome"],
            reason_code=data.get("reason_code"),
            requested_sats=int(data["requested_sats"]),
            destination=data.get("destination"),
            destination_kind=data.get("destination_kind"),
            allowlist_status=data.get("allowlist_status"),
            api_key_id=data.get("api_key_id"),
            caller_tag=data.get("caller_tag"),
            balance_at_decision_sats=(
                int(data["balance_at_decision_sats"])
                if data.get("balance_at_decision_sats") is not None
                else None
            ),
            thresholds=[Threshold.from_api(t) for t in data.get("thresholds", [])],
            binding_rule=data.get("binding_rule"),
            min_margin_pct=(
                float(data["min_margin_pct"])
                if data.get("min_margin_pct") is not None
                else None
            ),
            policy_snapshot=data.get("policy_snapshot"),
            policy_hash=data.get("policy_hash"),
            tx_id=data.get("tx_id"),
            created_at=_parse_dt(data["created_at"]),
        )
