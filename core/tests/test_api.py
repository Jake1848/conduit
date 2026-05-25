"""End-to-end smoke tests through the HTTP layer."""

import pytest


@pytest.mark.asyncio
async def test_health_is_public(client):
    # health should be reachable without an auth header
    headers = {}
    r = await client.get("/v1/health", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "version" in body and "network" in body


@pytest.mark.asyncio
async def test_status_requires_auth(client):
    r = await client.get("/v1/status", headers={"Authorization": ""})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_create_agent_attach_policy_and_pay(client):
    r = await client.post(
        "/v1/agents", json={"name": "compute-router-7", "daily_limit": 50_000}
    )
    assert r.status_code == 201, r.text
    agent = r.json()
    assert agent["name"] == "compute-router-7"
    agent_id = agent["id"]

    r = await client.post(
        f"/v1/agents/{agent_id}/policy",
        json={"max_per_hour": 10_000, "allowlist": ["02beef" + "00" * 31]},
    )
    assert r.status_code == 201, r.text

    # Allowlist blocks unknown destinations.
    r = await client.post(
        "/v1/payments/send",
        json={
            "agent_id": agent_id,
            "dest_pubkey": "02dead" + "00" * 31,
            "sats": 150,
            "memo": "dataset query",
        },
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "DESTINATION_NOT_ALLOWLISTED"

    # Allowed destination succeeds (mock LND auto-settles).
    r = await client.post(
        "/v1/payments/send",
        json={
            "agent_id": agent_id,
            "dest_pubkey": "02beef" + "00" * 31,
            "sats": 150,
            "memo": "dataset query",
        },
    )
    assert r.status_code == 201, r.text
    receipt = r.json()
    assert receipt["status"] == "settled"
    assert receipt["amount_sats"] == 150
    assert receipt["settled_in_ms"] is not None
    assert receipt["hash"]


@pytest.mark.asyncio
async def test_daily_limit_enforced_via_api(client):
    r = await client.post("/v1/agents", json={"name": "tight-budget", "daily_limit": 500})
    agent_id = r.json()["id"]

    # First payment within limit succeeds.
    r = await client.post(
        "/v1/payments/send",
        json={
            "agent_id": agent_id,
            "dest_pubkey": "02" + "11" * 32,
            "sats": 400,
        },
    )
    assert r.status_code == 201, r.text

    # Second payment that would exceed the daily limit is denied.
    r = await client.post(
        "/v1/payments/send",
        json={
            "agent_id": agent_id,
            "dest_pubkey": "02" + "22" * 32,
            "sats": 200,
        },
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "DAILY_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_invoice_creation(client):
    r = await client.post("/v1/agents", json={"name": "receiver-1"})
    agent_id = r.json()["id"]
    r = await client.post(
        "/v1/invoices", json={"agent_id": agent_id, "amount": 5000, "memo": "service x"}
    )
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["amount_sats"] == 5000
    assert inv["payment_request"].startswith("ln")
    assert len(inv["payment_hash"]) >= 32

    r = await client.get(f"/v1/invoices/{inv['id']}")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_scope_denied_for_read_key_writing(client):
    # Mint a read-only key.
    r = await client.post(
        "/v1/api-keys", json={"scope": "read", "label": "read-only"}
    )
    assert r.status_code == 201
    read_key = r.json()["secret"]

    # Read works.
    r = await client.get(
        "/v1/agents", headers={"Authorization": f"Bearer {read_key}"}
    )
    assert r.status_code == 200

    # Write is denied with 403.
    r = await client.post(
        "/v1/agents",
        json={"name": "should-fail"},
        headers={"Authorization": f"Bearer {read_key}"},
    )
    assert r.status_code == 403
