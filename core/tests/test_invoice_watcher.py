"""Invoice watcher — settles inbound invoices, credits the agent, fires webhook."""

from datetime import UTC, datetime

import pytest


@pytest.mark.asyncio
async def test_settled_invoice_credits_agent_and_fires_webhook(client, monkeypatch):
    """End-to-end: create invoice → simulate LND settling it → balance increased + webhook fired."""
    from conduit_core.db.database import SessionLocal
    from conduit_core.services.invoice_watcher import InvoiceWatcher
    from conduit_core.services.lnd import InvoiceUpdate, get_lnd

    r = await client.post("/v1/agents", json={"name": "receiver"})
    agent_id = r.json()["id"]

    r = await client.post(
        "/v1/invoices",
        json={"agent_id": agent_id, "amount": 5_000, "memo": "fee"},
    )
    assert r.status_code == 201, r.text
    inv = r.json()
    payment_hash = inv["payment_hash"]

    # Pre-settlement balance should be zero.
    bal = (await client.get(f"/v1/agents/{agent_id}/balance")).json()
    assert bal["available_sats"] == 0

    # Capture webhook deliveries instead of sending them.
    delivered: list[tuple[str, dict]] = []

    def fake_fire(event, payload):
        delivered.append((event, payload))

    monkeypatch.setattr(
        "conduit_core.services.invoice_watcher.fire_webhook", fake_fire
    )

    watcher = InvoiceWatcher(get_lnd(), SessionLocal)
    await watcher.process_update(
        InvoiceUpdate(
            payment_hash=payment_hash,
            amount_sats=5_000,
            state="SETTLED",
            settled_at=datetime.now(UTC),
        )
    )

    # Balance updated.
    bal = (await client.get(f"/v1/agents/{agent_id}/balance")).json()
    assert bal["available_sats"] == 5_000

    # Invoice marked settled.
    r = await client.get(f"/v1/invoices/{inv['id']}")
    assert r.json()["status"] == "settled"

    # Webhook payload was generated.
    assert any(e == "invoice.settled" for e, _ in delivered), delivered
    settled_payload = next(p for e, p in delivered if e == "invoice.settled")
    assert settled_payload["amount_sats"] == 5_000
    assert settled_payload["agent_id"] == agent_id
    assert settled_payload["payment_hash"] == payment_hash


@pytest.mark.asyncio
async def test_expired_invoice_marks_failed_no_credit(client, monkeypatch):
    from conduit_core.db.database import SessionLocal
    from conduit_core.services.invoice_watcher import InvoiceWatcher
    from conduit_core.services.lnd import InvoiceUpdate, get_lnd

    r = await client.post("/v1/agents", json={"name": "expired-receiver"})
    agent_id = r.json()["id"]

    r = await client.post(
        "/v1/invoices",
        json={"agent_id": agent_id, "amount": 1_234, "memo": "lapsed"},
    )
    payment_hash = r.json()["payment_hash"]
    inv_id = r.json()["id"]

    delivered: list[tuple[str, dict]] = []

    def fake_fire(event, payload):
        delivered.append((event, payload))

    monkeypatch.setattr(
        "conduit_core.services.invoice_watcher.fire_webhook", fake_fire
    )

    watcher = InvoiceWatcher(get_lnd(), SessionLocal)
    await watcher.process_update(
        InvoiceUpdate(payment_hash=payment_hash, amount_sats=0, state="CANCELED")
    )

    # Invoice marked failed.
    r = await client.get(f"/v1/invoices/{inv_id}")
    assert r.json()["status"] == "failed"
    # No credit — balance still zero.
    bal = (await client.get(f"/v1/agents/{agent_id}/balance")).json()
    assert bal["available_sats"] == 0
    # invoice.expired webhook fired.
    assert any(e == "invoice.expired" for e, _ in delivered)


@pytest.mark.asyncio
async def test_unknown_payment_hash_is_no_op(client, monkeypatch):
    """Settle events for hashes we don't own (foreign payments) must not error."""
    from conduit_core.db.database import SessionLocal
    from conduit_core.services.invoice_watcher import InvoiceWatcher
    from conduit_core.services.lnd import InvoiceUpdate, get_lnd

    delivered: list[tuple[str, dict]] = []

    def fake_fire(event, payload):
        delivered.append((event, payload))

    monkeypatch.setattr(
        "conduit_core.services.invoice_watcher.fire_webhook", fake_fire
    )

    watcher = InvoiceWatcher(get_lnd(), SessionLocal)
    # Should silently no-op.
    await watcher.process_update(
        InvoiceUpdate(payment_hash="00" * 32, amount_sats=100, state="SETTLED")
    )
    assert delivered == []


@pytest.mark.asyncio
async def test_duplicate_settle_does_not_double_credit(client, monkeypatch):
    """Idempotency — a second SETTLED for the same invoice must not credit again."""
    from conduit_core.db.database import SessionLocal
    from conduit_core.services.invoice_watcher import InvoiceWatcher
    from conduit_core.services.lnd import InvoiceUpdate, get_lnd

    r = await client.post("/v1/agents", json={"name": "idem"})
    agent_id = r.json()["id"]
    r = await client.post(
        "/v1/invoices", json={"agent_id": agent_id, "amount": 1_000}
    )
    payment_hash = r.json()["payment_hash"]

    def noop_fire(*a, **kw):
        return None

    monkeypatch.setattr(
        "conduit_core.services.invoice_watcher.fire_webhook", noop_fire
    )

    watcher = InvoiceWatcher(get_lnd(), SessionLocal)
    update = InvoiceUpdate(payment_hash=payment_hash, amount_sats=1_000, state="SETTLED")
    await watcher.process_update(update)
    await watcher.process_update(update)  # second time

    bal = (await client.get(f"/v1/agents/{agent_id}/balance")).json()
    assert bal["available_sats"] == 1_000, "second SETTLED must not double-credit"
