"""Regression: conduit_decisions projects the policy-engine Decision Record.

`_decision` maps the API's DecisionOut into the tool result. It MUST keep the
margin-bearing `thresholds[]` and the `binding_rule` (that's the headline — how
close a payment came to each limit), and it must emit ONLY the documented
READ-scope contract fields, so an upstream payload can never leak a secret into
the agent. Missing optional fields default rather than raise.
"""
from conduit_mcp.server import _decision

SAMPLE = {
    "id": "dec_123",
    "agent_id": "agt_abc",
    "outcome": "rejected",
    "reason_code": "PER_TRANSACTION_LIMIT_EXCEEDED",
    "requested_sats": 5000,
    "destination": "alice@example.com",
    "destination_kind": "bolt11",
    "allowlist_status": "allowed",
    "api_key_id": "key_1",
    "caller_tag": "agent-7",
    "balance_at_decision_sats": 100000,
    "thresholds": [
        {
            "rule": "per_transaction",
            "unit": "sats",
            "limit": 1000,
            "attempted": 5000,
            "current": 0,
            "margin_abs": -4000,
            "margin_pct": -400.0,
            "violated": True,
        },
    ],
    "binding_rule": "per_transaction",
    "min_margin_pct": -400.0,
    "policy_snapshot": {"max_per_transaction": 1000},
    "policy_hash": "abc123",
    "tx_id": None,
    "created_at": "2026-06-27T00:00:00Z",
}


def test_decision_keeps_margin_and_thresholds():
    out = _decision(SAMPLE)
    assert out["binding_rule"] == "per_transaction"
    assert out["thresholds"][0]["margin_abs"] == -4000  # the headline: how close
    assert out["thresholds"][0]["violated"] is True
    assert out["outcome"] == "rejected"
    assert out["reason_code"] == "PER_TRANSACTION_LIMIT_EXCEEDED"


def test_decision_does_not_leak_unexpected_fields():
    # Even if an upstream dict carried a secret, the projection only emits the
    # documented contract fields — never a preimage/secret into the agent.
    leaky = {**SAMPLE, "preimage": "deadbeef", "secret": "nope"}
    out = _decision(leaky)
    assert "preimage" not in out
    assert "secret" not in out


def test_decision_tolerates_missing_optional_fields():
    out = _decision({"id": "dec_x", "outcome": "settled"})
    assert out["id"] == "dec_x"
    assert out["thresholds"] == []  # defaulted, never KeyError
    assert out["binding_rule"] is None
