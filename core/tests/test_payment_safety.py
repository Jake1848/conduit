"""Regression tests for the four financial-safety fixes."""

import pytest


async def _credit(client, agent_id: str, sats: int) -> None:
    r = await client.post(
        f"/v1/agents/{agent_id}/credit", json={"sats": sats, "reason": "test setup"}
    )
    assert r.status_code == 201, r.text


# ---------- Fix #1: BOLT11 amount vs body.sats ----------

@pytest.mark.asyncio
async def test_bolt11_smaller_sats_is_rejected(client, monkeypatch):
    """An attacker submits a 1,000,000-sat BOLT11 with `sats=1`. Must be denied
    before the policy engine, before any debit."""
    from conduit_core.services.lnd import DecodedInvoice, get_lnd

    async def fake_decode(self, payment_request):
        return DecodedInvoice(
            payment_hash="a" * 64,
            amount_sats=1_000_000,   # invoice value
            destination="02" + "11" * 32,
            description="huge invoice",
            expiry=3600,
        )

    monkeypatch.setattr(type(get_lnd()), "decode_invoice", fake_decode)

    r = await client.post("/v1/agents", json={"name": "victim"})
    agent_id = r.json()["id"]
    await _credit(client, agent_id, 10_000)

    r = await client.post(
        "/v1/payments/send",
        json={
            "agent_id": agent_id,
            "payment_request": "lnbc10m1pmockinvoice",
            "sats": 1,
        },
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "INVALID_INPUT"
    assert "1000000" in r.json()["detail"]["detail"]

    # Balance untouched (no debit even though we crossed the route boundary).
    bal = (await client.get(f"/v1/agents/{agent_id}/balance")).json()
    assert bal["available_sats"] == 10_000


@pytest.mark.asyncio
async def test_bolt11_matching_sats_is_accepted(client, monkeypatch):
    """The honest path: caller's `sats` matches the invoice. Must succeed."""
    from conduit_core.services.lnd import DecodedInvoice, get_lnd

    async def fake_decode(self, payment_request):
        return DecodedInvoice(
            payment_hash="b" * 64,
            amount_sats=500,
            destination="02" + "22" * 32,
            description="matching",
            expiry=3600,
        )

    monkeypatch.setattr(type(get_lnd()), "decode_invoice", fake_decode)

    r = await client.post("/v1/agents", json={"name": "honest"})
    agent_id = r.json()["id"]
    await _credit(client, agent_id, 10_000)

    r = await client.post(
        "/v1/payments/send",
        json={
            "agent_id": agent_id,
            "payment_request": "lnbc500u1pmockinvoice",
            "sats": 500,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["amount_sats"] == 500


@pytest.mark.asyncio
async def test_bolt11_no_sats_uses_invoice_amount(client, monkeypatch):
    """Omitting sats on a fixed-amount invoice falls back to the embedded value."""
    from conduit_core.services.lnd import DecodedInvoice, get_lnd

    async def fake_decode(self, payment_request):
        return DecodedInvoice(
            payment_hash="c" * 64,
            amount_sats=750,
            destination="02" + "33" * 32,
            description="no sats",
            expiry=3600,
        )

    monkeypatch.setattr(type(get_lnd()), "decode_invoice", fake_decode)

    r = await client.post("/v1/agents", json={"name": "no-sats"})
    agent_id = r.json()["id"]
    await _credit(client, agent_id, 10_000)

    r = await client.post(
        "/v1/payments/send",
        json={
            "agent_id": agent_id,
            "payment_request": "lnbc750u1pmockinvoice",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["amount_sats"] == 750


# ---------- Fix #2: Lightning Address overcharge ----------

@pytest.mark.asyncio
async def test_lnurl_pay_overcharge_is_rejected(client, monkeypatch):
    """A malicious LNURL-pay server returns an invoice for 100x the requested
    sats. The route must decode and refuse before paying."""
    from conduit_core.services import wallet as wallet_module
    from conduit_core.services.lnd import DecodedInvoice, get_lnd

    async def fake_resolve(address, sats, memo):
        return "lnbc1m1pmaliciousinvoice"

    async def fake_decode(self, payment_request):
        # Returns 100,000 sats for the malicious invoice regardless of input.
        return DecodedInvoice(
            payment_hash="d" * 64,
            amount_sats=100_000,
            destination="02" + "44" * 32,
            description="malicious",
            expiry=3600,
        )

    monkeypatch.setattr(
        wallet_module, "resolve_lightning_address_to_invoice", fake_resolve
    )
    # Also patch the import inside payments.py.
    from conduit_core.routes import payments as payments_route

    monkeypatch.setattr(
        payments_route, "resolve_lightning_address_to_invoice", fake_resolve
    )
    monkeypatch.setattr(type(get_lnd()), "decode_invoice", fake_decode)

    r = await client.post("/v1/agents", json={"name": "lnurl-victim"})
    agent_id = r.json()["id"]
    await _credit(client, agent_id, 200_000)

    r = await client.post(
        "/v1/payments/pay",
        json={
            "agent_id": agent_id,
            "to": "evil@host.example",
            "sats": 1_000,
        },
    )
    assert r.status_code == 502, r.text
    assert r.json()["detail"]["code"] == "PAYMENT_FAILED"
    assert "100000" in r.json()["detail"]["detail"]

    # Balance must be untouched — refusal happens before debit.
    bal = (await client.get(f"/v1/agents/{agent_id}/balance")).json()
    assert bal["available_sats"] == 200_000


# ---------- Fix #3: unknown LND state leaves tx pending, no refund ----------

@pytest.mark.asyncio
async def test_lnd_error_leaves_pending_no_refund(client, monkeypatch):
    """If the LND HTTP call raises a non-PaymentFailed error (timeout, 5xx,
    parse error), the payment may have actually settled on LND. We must NOT
    refund the agent's balance — the tx stays pending with a reconciliation
    marker so the operator can manually verify via lookuppayment."""
    from conduit_core.errors import LNDError
    from conduit_core.services.lnd import get_lnd

    async def lnd_blowup(*a, **kw):
        raise LNDError("connection reset by peer mid-stream")

    monkeypatch.setattr(get_lnd(), "keysend", lnd_blowup)

    r = await client.post("/v1/agents", json={"name": "lnd-flaky"})
    agent_id = r.json()["id"]
    await _credit(client, agent_id, 10_000)
    bal_before = (await client.get(f"/v1/agents/{agent_id}/balance")).json()
    assert bal_before["available_sats"] == 10_000

    r = await client.post(
        "/v1/payments/send",
        json={
            "agent_id": agent_id,
            "dest_pubkey": "02" + "ee" * 32,
            "sats": 500,
        },
    )
    assert r.status_code == 502, r.text
    body = r.json()["detail"]
    assert body["code"] == "PAYMENT_FAILED"
    assert body.get("needs_reconciliation") is True
    assert "UNKNOWN" in body["detail"]
    tx_id = body["transaction_id"]

    # Balance is NOT refunded — the LND payment may still settle.
    bal_after = (await client.get(f"/v1/agents/{agent_id}/balance")).json()
    assert bal_after["available_sats"] == 10_000 - 505  # 500 + 1% fee budget

    # The tx is still pending with the reconciliation marker.
    r = await client.get(f"/v1/transactions/{tx_id}")
    tx = r.json()
    assert tx["status"] == "pending"
    # failure_reason is not in TransactionOut schema, so check via list
    r = await client.get(f"/v1/agents/{agent_id}/transactions")
    pending_tx = next(t for t in r.json()["data"] if t["id"] == tx_id)
    assert pending_tx["status"] == "pending"


@pytest.mark.asyncio
async def test_payment_failed_still_refunds(client, monkeypatch):
    """Sanity check that the explicit-failure refund path still works after
    the new LND-error branch was added."""
    from conduit_core.errors import PaymentFailed
    from conduit_core.services.lnd import get_lnd

    async def fail(*a, **kw):
        raise PaymentFailed("explicit lightning failure")

    monkeypatch.setattr(get_lnd(), "keysend", fail)

    r = await client.post("/v1/agents", json={"name": "explicit-fail"})
    agent_id = r.json()["id"]
    await _credit(client, agent_id, 10_000)

    r = await client.post(
        "/v1/payments/send",
        json={
            "agent_id": agent_id,
            "dest_pubkey": "02" + "ff" * 32,
            "sats": 500,
        },
    )
    assert r.status_code == 502
    # Balance fully refunded — explicit failure means money never moved.
    bal = (await client.get(f"/v1/agents/{agent_id}/balance")).json()
    assert bal["available_sats"] == 10_000
