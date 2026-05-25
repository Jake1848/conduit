"""SDK contract tests — mocks the API at the HTTP layer."""

import json
from datetime import datetime, timezone

import httpx
import pytest


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mock_transport():
    """A MockTransport that emulates the Conduit Core API just enough for these tests."""
    state: dict[str, dict] = {"agents": {}, "policies": {}}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
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

        if path.startswith("/v1/agents/") and path.endswith("/policy") and method == "POST":
            aid = path.split("/")[3]
            policy = {
                "id": f"pol_{aid}",
                "agent_id": aid,
                **{k: body.get(k) for k in
                   ("max_per_transaction", "max_per_hour", "max_per_day")},
                "max_per_minute_count": body.get("max_per_minute_count") or 60,
                "allowlist": body.get("allowlist") or [],
                "blocklist": body.get("blocklist") or [],
                "require_memo": body.get("require_memo", False),
                "enabled": body.get("enabled", True),
                "created_at": _now(),
                "updated_at": None,
            }
            state["policies"][aid] = policy
            return httpx.Response(201, json=policy)

        if path == "/v1/payments/send" and method == "POST":
            sats = body.get("sats", 0)
            aid = body.get("agent_id", "")
            policy = state["policies"].get(aid, {})
            if policy.get("max_per_day") and sats > policy["max_per_day"]:
                return httpx.Response(
                    403,
                    json={
                        "detail": {
                            "code": "DAILY_LIMIT_EXCEEDED",
                            "detail": f"{sats} > {policy['max_per_day']}",
                        }
                    },
                )
            return httpx.Response(
                201,
                json={
                    "id": "tx_test_1",
                    "agent_id": aid,
                    "status": "settled",
                    "hash": "deadbeef" * 8,
                    "amount_sats": sats,
                    "fee_sats": 1,
                    "settled_in_ms": 42,
                    "destination": body.get("dest_pubkey") or body.get("payment_request"),
                    "memo": body.get("memo"),
                    "created_at": _now(),
                },
            )

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


def test_create_agent_attach_policy_and_pay(sdk):
    agent = sdk.Agent.create(name="alpha", daily_limit=10_000)
    assert agent.id.startswith("agt_")
    assert agent.name == "alpha"

    agent.policy.attach(max_per_hour=5_000, allowlist=["02beef" + "00" * 31])

    receipt = agent.keysend(dest_pubkey="02" + "aa" * 32, sats=120, memo="hello")
    assert receipt.status == "settled"
    assert receipt.hash.startswith("deadbeef")
    assert receipt.settled_in_ms == 42
    assert receipt.amount_sats == 120


def test_policy_violation_raises_typed_error(sdk):
    agent = sdk.Agent.create(name="strict")
    agent.policy.attach(max_per_day=200)
    with pytest.raises(sdk.PolicyViolation) as e:
        agent.keysend(dest_pubkey="02" + "bb" * 32, sats=500)
    assert e.value.code == "DAILY_LIMIT_EXCEEDED"
