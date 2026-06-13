"""Payment reconciler — turns UNKNOWN-state pending sends into settled or
failed, refunding correctly along the way."""

from datetime import UTC, datetime, timedelta

import pytest


async def _credit(client, agent_id: str, sats: int) -> None:
    r = await client.post(
        f"/v1/agents/{agent_id}/credit", json={"sats": sats, "reason": "test"}
    )
    assert r.status_code == 201, r.text


async def _make_pending_send(
    client,
    sats: int,
    fee_budget: int,
    payment_hash: str,
    age_seconds: int = 0,
):
    """Create an agent + credit it + insert a pending outbound Transaction
    that simulates an UNKNOWN-state row left behind by an LND error."""
    from conduit_core.db.database import SessionLocal
    from conduit_core.db.models import Agent, Transaction
    from conduit_core.services.ids import tx_id as new_tx_id

    r = await client.post("/v1/agents", json={"name": f"a-{payment_hash[:8]}"})
    agent_id = r.json()["id"]
    await _credit(client, agent_id, sats + fee_budget + 10_000)
    bal_before = (await client.get(f"/v1/agents/{agent_id}/balance")).json()["available_sats"]

    # Manually debit and create the pending row, mimicking the state the
    # payment route would have left us in after an UNKNOWN-state LND error.
    async with SessionLocal() as session:
        agent = await session.get(Agent, agent_id)
        agent.balance_sats -= sats + fee_budget
        tx_id_value = new_tx_id()
        created = datetime.now(UTC) - timedelta(seconds=age_seconds)
        session.add(
            Transaction(
                id=tx_id_value,
                agent_id=agent_id,
                direction="send",
                amount_sats=sats,
                fee_sats=fee_budget,
                destination="02" + "ab" * 32,
                payment_hash=payment_hash,
                status="pending",
                memo="reconcile test",
                failure_reason="needs_reconciliation: simulated",
                created_at=created,
            )
        )
        await session.commit()
    return agent_id, tx_id_value, bal_before


@pytest.mark.asyncio
async def test_succeeded_lookup_settles_and_refunds_fee(client, monkeypatch):
    from conduit_core.db.database import SessionLocal
    from conduit_core.services import webhook_sender
    from conduit_core.services.lnd import PaymentLookup, get_lnd
    from conduit_core.services.reconciler import PaymentReconciler

    delivered: list[tuple[str, dict]] = []

    def fake_fire(event, payload):
        delivered.append((event, payload))

    monkeypatch.setattr(webhook_sender, "fire", fake_fire)
    # Patch the imported name inside the reconciler too.
    from conduit_core.services import reconciler as rec_module

    monkeypatch.setattr(rec_module, "fire_webhook", fake_fire)

    payment_hash = "ab" * 32
    agent_id, tx_id_value, bal_before = await _make_pending_send(
        client, sats=1_000, fee_budget=10, payment_hash=payment_hash, age_seconds=120
    )

    async def lookup_success(self, ph):
        assert ph == payment_hash
        return PaymentLookup(
            status="SUCCEEDED",
            payment_hash=ph,
            fee_sats=3,  # actual fee under budget
            payment_preimage="cd" * 32,
        )

    monkeypatch.setattr(type(get_lnd()), "lookup_payment", lookup_success)

    rec = PaymentReconciler(get_lnd(), SessionLocal, min_age_seconds=0)
    changed = await rec.reconcile_one(tx_id_value)
    assert changed is True

    r = await client.get(f"/v1/transactions/{tx_id_value}")
    tx = r.json()
    assert tx["status"] == "settled"
    assert tx["fee_sats"] == 3  # actual, not budgeted

    # Fee budget was 10, actual 3 → refund of 7.
    bal_after = (await client.get(f"/v1/agents/{agent_id}/balance")).json()["available_sats"]
    assert bal_after == bal_before - 1_000 - 3, (
        f"expected {bal_before - 1003}, got {bal_after}"
    )
    # Webhook fired with reconciled=true.
    assert any(
        e == "payment.settled" and p.get("reconciled") is True for e, p in delivered
    )


@pytest.mark.asyncio
async def test_failed_lookup_refunds_full_debit(client, monkeypatch):
    from conduit_core.db.database import SessionLocal
    from conduit_core.services.lnd import PaymentLookup, get_lnd
    from conduit_core.services.reconciler import PaymentReconciler

    delivered: list[tuple[str, dict]] = []

    def fake_fire(event, payload):
        delivered.append((event, payload))

    from conduit_core.services import reconciler as rec_module

    monkeypatch.setattr(rec_module, "fire_webhook", fake_fire)

    payment_hash = "cd" * 32
    agent_id, tx_id_value, bal_before = await _make_pending_send(
        client, sats=2_000, fee_budget=20, payment_hash=payment_hash, age_seconds=120
    )

    async def lookup_fail(self, ph):
        return PaymentLookup(
            status="FAILED",
            payment_hash=ph,
            failure_reason="NO_ROUTE",
        )

    monkeypatch.setattr(type(get_lnd()), "lookup_payment", lookup_fail)

    rec = PaymentReconciler(get_lnd(), SessionLocal, min_age_seconds=0)
    assert (await rec.reconcile_one(tx_id_value)) is True

    r = await client.get(f"/v1/transactions/{tx_id_value}")
    tx = r.json()
    assert tx["status"] == "failed"

    # Full debit refunded — balance restored to before the pending row.
    bal_after = (await client.get(f"/v1/agents/{agent_id}/balance")).json()["available_sats"]
    assert bal_after == bal_before

    assert any(
        e == "payment.failed" and p.get("reconciled") is True for e, p in delivered
    )


@pytest.mark.asyncio
async def test_reconcile_is_idempotent_no_double_refund(client, monkeypatch):
    """Audit M13: the route-refund-vs-reconcile-sweep double-process is guarded by
    a status re-check under the agent lock. Reconciling the SAME pending send
    twice must refund EXACTLY once — the second pass sees a non-pending row and
    no-ops, so the balance is never restored twice (double-spend the other way)."""
    from conduit_core.db.database import SessionLocal
    from conduit_core.services.lnd import PaymentLookup, get_lnd
    from conduit_core.services.reconciler import PaymentReconciler

    payment_hash = "ef" * 32
    agent_id, tx_id_value, bal_before = await _make_pending_send(
        client, sats=3_000, fee_budget=30, payment_hash=payment_hash, age_seconds=120
    )

    async def lookup_fail(self, ph):
        return PaymentLookup(status="FAILED", payment_hash=ph, failure_reason="NO_ROUTE")

    monkeypatch.setattr(type(get_lnd()), "lookup_payment", lookup_fail)
    rec = PaymentReconciler(get_lnd(), SessionLocal, min_age_seconds=0)

    assert (await rec.reconcile_one(tx_id_value)) is True  # first pass refunds
    await rec.reconcile_one(tx_id_value)  # second pass must be a no-op
    bal_after = (await client.get(f"/v1/agents/{agent_id}/balance")).json()["available_sats"]
    assert bal_after == bal_before, "double-refund: balance restored more than once"


@pytest.mark.asyncio
async def test_in_flight_lookup_leaves_pending(client, monkeypatch):
    from conduit_core.db.database import SessionLocal
    from conduit_core.services import reconciler as rec_module
    from conduit_core.services.lnd import PaymentLookup, get_lnd
    from conduit_core.services.reconciler import PaymentReconciler

    monkeypatch.setattr(rec_module, "fire_webhook", lambda *a, **kw: None)

    payment_hash = "ef" * 32
    agent_id, tx_id_value, bal_before = await _make_pending_send(
        client, sats=500, fee_budget=5, payment_hash=payment_hash, age_seconds=120
    )

    async def lookup_inflight(self, ph):
        return PaymentLookup(status="IN_FLIGHT", payment_hash=ph)

    monkeypatch.setattr(type(get_lnd()), "lookup_payment", lookup_inflight)

    rec = PaymentReconciler(get_lnd(), SessionLocal, min_age_seconds=0)
    assert (await rec.reconcile_one(tx_id_value)) is False

    r = await client.get(f"/v1/transactions/{tx_id_value}")
    assert r.json()["status"] == "pending"

    # Balance unchanged.
    bal_after = (await client.get(f"/v1/agents/{agent_id}/balance")).json()["available_sats"]
    assert bal_after == bal_before - 505


@pytest.mark.asyncio
async def test_no_payment_hash_is_skipped(client, monkeypatch):
    """Legacy pending rows (no payment_hash) cannot be reconciled — they must
    be left alone for manual resolution."""
    from conduit_core.db.database import SessionLocal
    from conduit_core.db.models import Agent, Transaction
    from conduit_core.services import reconciler as rec_module
    from conduit_core.services.ids import tx_id as new_tx_id
    from conduit_core.services.lnd import get_lnd
    from conduit_core.services.reconciler import PaymentReconciler

    looked_up: list[str] = []

    async def fake_lookup(self, ph):
        looked_up.append(ph)
        raise AssertionError("must not be called for hashless rows")

    monkeypatch.setattr(type(get_lnd()), "lookup_payment", fake_lookup)
    monkeypatch.setattr(rec_module, "fire_webhook", lambda *a, **kw: None)

    r = await client.post("/v1/agents", json={"name": "legacy-no-hash"})
    agent_id = r.json()["id"]
    await _credit(client, agent_id, 1_000)

    async with SessionLocal() as session:
        agent = await session.get(Agent, agent_id)
        agent.balance_sats -= 500
        tx_id_value = new_tx_id()
        session.add(
            Transaction(
                id=tx_id_value,
                agent_id=agent_id,
                direction="send",
                amount_sats=500,
                fee_sats=5,
                destination="02" + "11" * 32,
                payment_hash=None,
                status="pending",
                created_at=datetime.now(UTC) - timedelta(minutes=10),
            )
        )
        await session.commit()

    rec = PaymentReconciler(get_lnd(), SessionLocal, min_age_seconds=0)
    assert (await rec.reconcile_one(tx_id_value)) is False
    assert looked_up == []


@pytest.mark.asyncio
async def test_sweep_skips_recent_pending(client, monkeypatch):
    """Don't touch payments that just started — they're probably still in
    flight under LND's normal payment timeout."""
    from conduit_core.db.database import SessionLocal
    from conduit_core.services import reconciler as rec_module
    from conduit_core.services.lnd import get_lnd
    from conduit_core.services.reconciler import PaymentReconciler

    monkeypatch.setattr(rec_module, "fire_webhook", lambda *a, **kw: None)

    async def must_not_lookup(self, ph):
        raise AssertionError("recent rows must not be looked up")

    monkeypatch.setattr(type(get_lnd()), "lookup_payment", must_not_lookup)

    # Create a pending row aged 5s, with min_age_seconds=60.
    payment_hash = "01" * 32
    _agent, _tx, _ = await _make_pending_send(
        client, sats=100, fee_budget=1, payment_hash=payment_hash, age_seconds=5
    )

    rec = PaymentReconciler(get_lnd(), SessionLocal, min_age_seconds=60)
    changes = await rec.sweep()
    assert changes == 0


@pytest.mark.asyncio
async def test_end_to_end_lnd_error_then_reconcile(client, monkeypatch):
    """Trigger an LNDError during payment (UNKNOWN state). The pending row
    is left with the balance debited. Then a reconciler sweep that finds
    SUCCEEDED clears it up."""
    from conduit_core.db.database import SessionLocal
    from conduit_core.errors import LNDError
    from conduit_core.services import reconciler as rec_module
    from conduit_core.services.lnd import PaymentLookup, get_lnd
    from conduit_core.services.reconciler import PaymentReconciler

    delivered: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        rec_module, "fire_webhook", lambda e, p: delivered.append((e, p))
    )

    r = await client.post("/v1/agents", json={"name": "e2e-recon"})
    agent_id = r.json()["id"]
    await _credit(client, agent_id, 10_000)

    # Cause the payment route to fail with LNDError (UNKNOWN state).
    async def lnd_blowup(*a, **kw):
        raise LNDError("simulated network blip")

    monkeypatch.setattr(get_lnd(), "keysend", lnd_blowup)

    r = await client.post(
        "/v1/payments/send",
        json={"agent_id": agent_id, "dest_pubkey": "02" + "22" * 32, "sats": 200},
    )
    assert r.status_code == 502
    tx_id_value = r.json()["detail"]["transaction_id"]

    # Balance debited, row pending.
    bal_after_err = (
        await client.get(f"/v1/agents/{agent_id}/balance")
    ).json()["available_sats"]
    # 200 payment + 2 routing budget (1%) + 1 platform fee (0.5%, round(1.0)=1).
    assert bal_after_err == 10_000 - 203

    # The pending row has a payment_hash now (post-fix).
    async with SessionLocal() as session:
        from conduit_core.db.models import Transaction

        tx = await session.get(Transaction, tx_id_value)
        assert tx.payment_hash, "payment_hash must be set on pending row"
        captured_hash = tx.payment_hash

    # Now simulate LND saying "yep, it did succeed" — the payment actually
    # landed despite the HTTP error.
    async def lookup_success(self, ph):
        assert ph == captured_hash
        return PaymentLookup(
            status="SUCCEEDED",
            payment_hash=ph,
            fee_sats=1,
            payment_preimage="aa" * 32,
        )

    monkeypatch.setattr(type(get_lnd()), "lookup_payment", lookup_success)

    rec = PaymentReconciler(get_lnd(), SessionLocal, min_age_seconds=0)
    assert (await rec.reconcile_one(tx_id_value)) is True

    r = await client.get(f"/v1/transactions/{tx_id_value}")
    assert r.json()["status"] == "settled"

    # Routing-fee refund of 1 sat (budget 2 - actual 1); platform fee (1) is KEPT.
    bal_final = (await client.get(f"/v1/agents/{agent_id}/balance")).json()["available_sats"]
    assert bal_final == 10_000 - 202  # 200 payment + 1 actual routing + 1 platform fee
