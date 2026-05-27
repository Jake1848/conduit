"""Idempotency-Key handling on /v1/payments/{send,pay}.

Goal: a network-blip retry must NOT cause a second Lightning payment.
"""

import pytest


async def _credit(client, agent_id: str, sats: int) -> None:
    r = await client.post(
        f"/v1/agents/{agent_id}/credit", json={"sats": sats, "reason": "test setup"}
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_same_key_returns_cached_response(client):
    """Second request with same Idempotency-Key returns the FIRST response
    without re-executing the payment."""
    r = await client.post("/v1/agents", json={"name": "idem-1"})
    agent_id = r.json()["id"]
    await _credit(client, agent_id, 10_000)

    payload = {
        "agent_id": agent_id,
        "dest_pubkey": "02" + "aa" * 32,
        "sats": 150,
        "memo": "idem test",
    }
    headers = {"Idempotency-Key": "test-key-abc-123"}

    r1 = await client.post("/v1/payments/send", json=payload, headers=headers)
    assert r1.status_code == 201, r1.text
    tx_id_1 = r1.json()["id"]

    r2 = await client.post("/v1/payments/send", json=payload, headers=headers)
    assert r2.status_code == 201, r2.text
    # SAME transaction id — proves second request returned cached response
    # rather than running a second payment.
    assert r2.json()["id"] == tx_id_1
    assert r2.json() == r1.json()

    # And the agent's transaction list contains exactly ONE settled send.
    r = await client.get(f"/v1/agents/{agent_id}/transactions?direction=send")
    txns = r.json()["data"]
    assert len([t for t in txns if t["status"] == "settled"]) == 1


@pytest.mark.asyncio
async def test_same_key_different_body_is_409(client):
    """Reusing a key with a different body must NOT silently return the
    cached response — that would be a worse bug. Return 409."""
    r = await client.post("/v1/agents", json={"name": "idem-2"})
    agent_id = r.json()["id"]
    await _credit(client, agent_id, 10_000)

    headers = {"Idempotency-Key": "test-key-conflict"}

    r1 = await client.post(
        "/v1/payments/send",
        json={"agent_id": agent_id, "dest_pubkey": "02" + "bb" * 32, "sats": 100},
        headers=headers,
    )
    assert r1.status_code == 201

    r2 = await client.post(
        "/v1/payments/send",
        json={"agent_id": agent_id, "dest_pubkey": "02" + "cc" * 32, "sats": 999},
        headers=headers,
    )
    assert r2.status_code == 409, r2.text
    assert r2.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.asyncio
async def test_failure_response_is_cached(client):
    """A retry of an Idempotency-Key whose first call failed returns the
    same failure — not a fresh attempt that might succeed and partially
    drift state."""
    r = await client.post("/v1/agents", json={"name": "broke-idem"})
    agent_id = r.json()["id"]
    # No credit — first payment will fail with INSUFFICIENT_BALANCE.

    payload = {
        "agent_id": agent_id,
        "dest_pubkey": "02" + "dd" * 32,
        "sats": 500,
    }
    headers = {"Idempotency-Key": "test-key-fail"}

    r1 = await client.post("/v1/payments/send", json=payload, headers=headers)
    assert r1.status_code == 402
    assert r1.json()["detail"]["code"] == "INSUFFICIENT_BALANCE"

    # Now credit so a fresh call WOULD succeed.
    await _credit(client, agent_id, 10_000)

    # But with the same Idempotency-Key, we still return the cached failure.
    r2 = await client.post("/v1/payments/send", json=payload, headers=headers)
    assert r2.status_code == 402
    assert r2.json()["detail"]["code"] == "INSUFFICIENT_BALANCE"

    # Balance untouched (no payment executed on the retry).
    bal = (await client.get(f"/v1/agents/{agent_id}/balance")).json()
    assert bal["available_sats"] == 10_000


@pytest.mark.asyncio
async def test_no_idempotency_header_means_fresh_each_time(client):
    """Without the header, each request is a fresh payment."""
    r = await client.post("/v1/agents", json={"name": "no-idem"})
    agent_id = r.json()["id"]
    await _credit(client, agent_id, 10_000)

    payload = {
        "agent_id": agent_id,
        "dest_pubkey": "02" + "ee" * 32,
        "sats": 100,
    }
    r1 = await client.post("/v1/payments/send", json=payload)
    r2 = await client.post("/v1/payments/send", json=payload)
    assert r1.status_code == 201
    assert r2.status_code == 201
    # Different transaction IDs — both ran.
    assert r1.json()["id"] != r2.json()["id"]


@pytest.mark.asyncio
async def test_idempotency_is_scoped_to_api_key(client):
    """Two different API keys using the same Idempotency-Key value do not
    collide — each gets its own cache entry."""
    # Mint a second write key.
    r = await client.post(
        "/v1/api-keys", json={"scope": "write", "label": "second"}
    )
    assert r.status_code == 201
    second_key = r.json()["secret"]

    r = await client.post("/v1/agents", json={"name": "alice-idem"})
    alice = r.json()["id"]
    await _credit(client, alice, 10_000)
    r = await client.post("/v1/agents", json={"name": "bob-idem"})
    bob = r.json()["id"]
    await _credit(client, bob, 10_000)

    same_key = {"Idempotency-Key": "shared-value"}

    # Alice's request via the bootstrap key.
    r1 = await client.post(
        "/v1/payments/send",
        json={"agent_id": alice, "dest_pubkey": "02" + "11" * 32, "sats": 50},
        headers=same_key,
    )
    assert r1.status_code == 201

    # Bob's request via the second key — same Idempotency-Key value, different
    # API key. Must NOT return Alice's response.
    r2 = await client.post(
        "/v1/payments/send",
        json={"agent_id": bob, "dest_pubkey": "02" + "22" * 32, "sats": 75},
        headers={**same_key, "Authorization": f"Bearer {second_key}"},
    )
    assert r2.status_code == 201
    assert r2.json()["amount_sats"] == 75
    assert r2.json()["id"] != r1.json()["id"]
