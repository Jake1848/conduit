"""SDK contract tests for the inspectable Decision Record — mocks the API at the
HTTP layer (mirrors test_sdk_against_core.py)."""

import json
from datetime import datetime, timezone

import httpx
import pytest


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# A settled, ALLOWED decision that nearly hit its daily cap (positive margin) and
# a rejected one that blew past it (negative margin) — the headline margin data.
def _settled_decision(agent_id: str) -> dict:
    return {
        "id": "dec_settled_1",
        "agent_id": agent_id,
        "outcome": "settled",
        "reason_code": None,
        "requested_sats": 900,
        "destination": "02" + "aa" * 32,
        "destination_kind": "keysend",
        "allowlist_status": "allowed",
        "api_key_id": "key_abc",
        "caller_tag": "crawler",
        "balance_at_decision_sats": 50_000,
        "thresholds": [
            {
                "rule": "daily",
                "unit": "sats",
                "limit": 10_000,
                "attempted": 900,
                "current": 9_000,
                "margin_abs": 100,
                "margin_pct": 1.0,
                "violated": False,
            }
        ],
        "binding_rule": "daily",
        "min_margin_pct": 1.0,
        "policy_snapshot": {"max_per_day": 10_000},
        "policy_hash": "sha256:abc",
        "tx_id": "tx_test_1",
        "created_at": _now(),
    }


def _rejected_decision(agent_id: str) -> dict:
    return {
        "id": "dec_rejected_2",
        "agent_id": agent_id,
        "outcome": "rejected",
        "reason_code": "DAILY_LIMIT_EXCEEDED",
        "requested_sats": 5_000,
        "destination": "02" + "bb" * 32,
        "destination_kind": "keysend",
        "allowlist_status": "allowed",
        "api_key_id": "key_abc",
        "caller_tag": None,
        "balance_at_decision_sats": 50_000,
        "thresholds": [
            {
                "rule": "daily",
                "unit": "sats",
                "limit": 10_000,
                "attempted": 5_000,
                "current": 9_000,
                "margin_abs": -4_000,
                "margin_pct": -40.0,
                "violated": True,
            }
        ],
        "binding_rule": "daily",
        "min_margin_pct": -40.0,
        "policy_snapshot": {"max_per_day": 10_000},
        "policy_hash": "sha256:abc",
        "tx_id": None,
        "created_at": _now(),
    }


def _mock_transport():
    """A MockTransport emulating the read-only Decision Record API."""
    state: dict[str, dict] = {"agents": {}}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        outcome = request.url.params.get("outcome")
        body = json.loads(request.content) if request.content else {}

        if path == "/v1/agents" and method == "POST":
            aid = f"agt_{len(state['agents'])}xyz"
            agent = {
                "id": aid,
                "name": body["name"],
                "pubkey": None,
                "active": True,
                "created_at": _now(),
            }
            state["agents"][aid] = agent
            return httpx.Response(201, json=agent)

        # GET /v1/agents/{id}/decisions and GET /v1/decisions/recent — same shape.
        if method == "GET" and (
            (path.startswith("/v1/agents/") and path.endswith("/decisions"))
            or path == "/v1/decisions/recent"
        ):
            aid = path.split("/")[3] if path.startswith("/v1/agents/") else "agt_0xyz"
            decisions = [_rejected_decision(aid), _settled_decision(aid)]
            if outcome:
                decisions = [d for d in decisions if d["outcome"] == outcome]
            return httpx.Response(200, json={"data": decisions, "has_more": False})

        if path.startswith("/v1/decisions/") and method == "GET":
            did = path.split("/")[3]
            aid = "agt_0xyz"
            doc = _rejected_decision(aid) if "rejected" in did else _settled_decision(aid)
            doc["id"] = did
            return httpx.Response(200, json=doc)

        return httpx.Response(404, json={"detail": {"code": "NOT_FOUND", "detail": path}})

    return httpx.MockTransport(handler)


@pytest.fixture
def sdk(monkeypatch):
    import conduit
    from conduit.client import Conduit
    import conduit.client as cc

    transport = _mock_transport()
    orig = Conduit.__init__

    def patched(self, *a, **kw):
        orig(self, *a, **kw)
        self._client = httpx.Client(
            base_url="http://mock",
            transport=transport,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )

    monkeypatch.setattr(Conduit, "__init__", patched)
    monkeypatch.setenv("CONDUIT_API_KEY", "ck_test_x")
    conduit.api_key = "ck_test_x"
    conduit.base_url = "http://mock"
    cc._default = None
    yield conduit
    cc._default = None


def test_agent_decisions_expose_margin(sdk):
    agent = sdk.Agent.create(name="alpha")
    decisions = agent.decisions()
    assert [d.id for d in decisions] == ["dec_rejected_2", "dec_settled_1"]

    rejected, settled = decisions
    assert rejected.outcome == "rejected"
    assert rejected.reason_code == "DAILY_LIMIT_EXCEEDED"
    assert rejected.binding_rule == "daily"
    assert rejected.min_margin_pct == -40.0
    assert rejected.tx_id is None

    # The headline margin: present and negative on the violated threshold.
    t = rejected.thresholds[0]
    assert isinstance(t, sdk.Threshold)
    assert t.rule == "daily"
    assert t.margin_abs == -4_000
    assert t.margin_pct == -40.0
    assert t.violated is True

    # A near-miss-that-passed still carries its (positive) margin.
    assert settled.outcome == "settled"
    assert settled.thresholds[0].margin_abs == 100
    assert settled.thresholds[0].violated is False
    assert settled.tx_id == "tx_test_1"


def test_agent_decisions_outcome_filter(sdk):
    agent = sdk.Agent.create(name="strict")
    rejected = agent.decisions(outcome="rejected")
    assert len(rejected) == 1
    assert all(d.outcome == "rejected" for d in rejected)


def test_client_list_decisions_agent_and_fleet(sdk):
    client = sdk.ConduitClient(base_url="http://mock", api_key="ck_test_x")

    agent = client.create_agent("router")
    per_agent = client.list_decisions(agent.id)
    assert {d.agent_id for d in per_agent} == {agent.id}

    # No agent_id → fleet-wide /v1/decisions/recent.
    fleet = client.list_decisions(outcome="rejected", limit=10)
    assert len(fleet) == 1
    assert fleet[0].outcome == "rejected"


def test_client_get_decision(sdk):
    client = sdk.ConduitClient(base_url="http://mock", api_key="ck_test_x")
    d = client.get_decision("dec_rejected_2")
    assert d.id == "dec_rejected_2"
    assert d.outcome == "rejected"
    assert d.thresholds[0].margin_abs == -4_000


def test_decision_is_frozen(sdk):
    client = sdk.ConduitClient(base_url="http://mock", api_key="ck_test_x")
    d = client.get_decision("dec_settled_1")
    with pytest.raises(Exception):
        d.outcome = "failed"  # frozen dataclass — immutable
