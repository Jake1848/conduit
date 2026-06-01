"""Tests for the dashboard-facing additions: balance_sats on the agent list,
GET /v1/metrics, and GET /v1/transactions/recent."""

import pytest


async def _credit(client, agent_id: str, sats: int) -> None:
    r = await client.post(f"/v1/agents/{agent_id}/credit", json={"sats": sats, "reason": "test"})
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_agent_list_includes_balance_sats(client):
    r = await client.post("/v1/agents", json={"name": "bal-agent"})
    agent_id = r.json()["id"]
    await _credit(client, agent_id, 7000)

    r = await client.get("/v1/agents")
    assert r.status_code == 200, r.text
    agents = {a["id"]: a for a in r.json()["data"]}
    assert "balance_sats" in agents[agent_id]
    assert agents[agent_id]["balance_sats"] == 7000


@pytest.mark.asyncio
async def test_metrics_shape_and_treasury(client):
    r = await client.post("/v1/agents", json={"name": "metrics-agent"})
    agent_id = r.json()["id"]
    await _credit(client, agent_id, 12_345)

    r = await client.get("/v1/metrics")
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["treasury_sats"] >= 12_345
    assert m["total_agents"] >= 1
    assert m["active_agents"] >= 1
    assert len(m["hourly"]) == 24
    for h in m["hourly"]:
        assert {"hour", "count", "volume_sats"} <= set(h)
    assert isinstance(m["top_agents"], list)
    # the agent we just credited has a 'receive' tx today → should appear
    assert any(t["agent_id"] == agent_id for t in m["top_agents"])


@pytest.mark.asyncio
async def test_recent_transactions_global(client):
    r = await client.post("/v1/agents", json={"name": "recent-agent"})
    agent_id = r.json()["id"]
    await _credit(client, agent_id, 100_000)
    r = await client.post(
        "/v1/payments/send",
        json={"agent_id": agent_id, "dest_pubkey": "02" + "ab" * 32, "sats": 500},
    )
    assert r.status_code == 201, r.text

    r = await client.get("/v1/transactions/recent?limit=10")
    assert r.status_code == 200, r.text  # 'recent' not captured as a tx id
    body = r.json()
    assert "data" in body and "has_more" in body
    assert any(t["agent_id"] == agent_id for t in body["data"])


@pytest.mark.asyncio
async def test_metrics_requires_auth(client):
    r = await client.get("/v1/metrics", headers={"Authorization": ""})
    assert r.status_code == 401
