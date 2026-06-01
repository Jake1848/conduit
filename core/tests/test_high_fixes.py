"""Tests for the HIGH/MEDIUM audit fixes: 429 envelope, zero-amount BOLT11,
and the 16-char API-key prefix discriminator."""

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient


# ---------------- HIGH 3: 429 envelope is nested under `detail` ----------------
@pytest.mark.asyncio
async def test_rate_limit_429_envelope_is_nested():
    from fastapi import FastAPI

    from conduit_core.middleware import RateLimitMiddleware

    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    # burst=1 → first request consumes the only token, second is denied.
    app.add_middleware(
        RateLimitMiddleware,
        settings=SimpleNamespace(rate_limit_per_minute=60, rate_limit_burst=1),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        assert (await c.get("/ping")).status_code == 200
        r = await c.get("/ping")
    assert r.status_code == 429
    body = r.json()
    # Must match every other error envelope: {"detail": {"code": ...}}
    assert isinstance(body.get("detail"), dict), body
    assert body["detail"]["code"] == "RATE_LIMITED"
    assert body["detail"]["retry_after"] >= 1
    assert "Retry-After" in r.headers


# ---------------- HIGH 2: zero-amount BOLT11 forwards the amount ----------------
@pytest.mark.asyncio
async def test_zero_amount_bolt11_send_forwards_amount(client):
    from conduit_core.services.lnd import get_lnd

    r = await client.post("/v1/agents", json={"name": "zero-amt"})
    agent_id = r.json()["id"]
    await client.post(f"/v1/agents/{agent_id}/credit", json={"sats": 50_000, "reason": "t"})

    # A real zero-amount invoice (decode reports amount_sats == 0).
    inv = await get_lnd().create_invoice(0, "zero-amount", 3600)

    r = await client.post(
        "/v1/payments/send",
        json={"agent_id": agent_id, "payment_request": inv.payment_request, "sats": 1234},
    )
    assert r.status_code == 201, r.text
    receipt = r.json()
    assert receipt["status"] == "settled"
    assert receipt["amount_sats"] == 1234  # the caller-supplied amount was used


@pytest.mark.asyncio
async def test_zero_amount_bolt11_without_sats_rejected(client):
    """The route rejects a zero-amount invoice with no `sats` BEFORE paying."""
    from conduit_core.services.lnd import get_lnd

    r = await client.post("/v1/agents", json={"name": "zero-amt-2"})
    agent_id = r.json()["id"]
    await client.post(f"/v1/agents/{agent_id}/credit", json={"sats": 50_000, "reason": "t"})
    inv = await get_lnd().create_invoice(0, "zero-amount", 3600)

    r = await client.post(
        "/v1/payments/send",
        json={"agent_id": agent_id, "payment_request": inv.payment_request},
    )
    assert r.status_code in (400, 422), r.text  # InvalidInput: zero-amount requires sats
    assert r.json()["detail"]["code"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_mock_pay_invoice_mirrors_lnd_zero_amount_rule(client):
    """The mock now rejects a zero-amount invoice without an explicit amount,
    mirroring real LND — so the missing-amount path is actually exercised."""
    from conduit_core.errors import PaymentFailed
    from conduit_core.services.lnd import get_lnd

    lnd = get_lnd()
    inv = await lnd.create_invoice(0, "zero", 3600)
    with pytest.raises(PaymentFailed):
        await lnd.pay_invoice(inv.payment_request, max_fee_sats=10)
    # With an explicit amount it succeeds.
    res = await lnd.pay_invoice(inv.payment_request, max_fee_sats=10, amount_sats=777)
    assert res.amount_sats == 777


# ---------------- MEDIUM c: 16-char prefix discriminator ----------------
@pytest.mark.asyncio
async def test_new_api_key_uses_16char_prefix_and_authenticates(client):
    r = await client.post("/v1/api-keys", json={"scope": "read", "label": "disc"})
    assert r.status_code == 201, r.text
    secret = r.json()["secret"]

    # The stored prefix is now the 16-char discriminator (not just the 8-char network prefix).
    keys = (await client.get("/v1/api-keys")).json()["data"]
    new_key = next(k for k in keys if k["label"] == "disc")
    assert len(new_key["prefix"]) == 16, new_key["prefix"]

    # And the key authenticates (auth resolves it via that discriminator).
    r = await client.get("/v1/agents", headers={"Authorization": f"Bearer {secret}"})
    assert r.status_code == 200
