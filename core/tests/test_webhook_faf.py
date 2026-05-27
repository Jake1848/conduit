"""Webhook fire-and-forget — a slow/erroring webhook must not block or
fail the originating payment route."""

import asyncio

import pytest


async def _credit(client, agent_id: str, sats: int) -> None:
    r = await client.post(
        f"/v1/agents/{agent_id}/credit", json={"sats": sats, "reason": "setup"}
    )
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_slow_webhook_does_not_block_payment(client, monkeypatch):
    """If the webhook delivery takes 10s, the payment response should still
    return promptly (well under the slow-webhook wait)."""
    import time as _time

    from conduit_core.services import webhook_sender

    started = _time.perf_counter()

    async def slow_deliver(event, payload, **kw):
        # Pretend the consumer's server is taking forever.
        await asyncio.sleep(5.0)

    monkeypatch.setattr(webhook_sender, "deliver", slow_deliver)

    r = await client.post("/v1/agents", json={"name": "fast-route"})
    agent_id = r.json()["id"]
    await _credit(client, agent_id, 10_000)

    r = await client.post(
        "/v1/payments/send",
        json={
            "agent_id": agent_id,
            "dest_pubkey": "02" + "01" * 32,
            "sats": 100,
        },
    )
    elapsed = _time.perf_counter() - started

    assert r.status_code == 201, r.text
    assert elapsed < 2.0, (
        f"payment took {elapsed:.2f}s — the slow webhook is blocking the route"
    )


@pytest.mark.asyncio
async def test_failing_webhook_does_not_turn_payment_into_500(client, monkeypatch):
    """Even if webhook delivery raises, the payment response is still 201."""
    from conduit_core.services import webhook_sender

    async def boom_deliver(event, payload, **kw):
        raise RuntimeError("downstream is on fire")

    monkeypatch.setattr(webhook_sender, "deliver", boom_deliver)

    r = await client.post("/v1/agents", json={"name": "safe-route"})
    agent_id = r.json()["id"]
    await _credit(client, agent_id, 10_000)

    r = await client.post(
        "/v1/payments/send",
        json={
            "agent_id": agent_id,
            "dest_pubkey": "02" + "02" * 32,
            "sats": 50,
        },
    )
    assert r.status_code == 201, r.text

    # Drain any in-flight task so it doesn't leak into the next test.
    await webhook_sender.flush(timeout=2.0)


@pytest.mark.asyncio
async def test_fire_returns_immediately(client, monkeypatch):
    """Unit-level: fire() returns before deliver() runs."""
    import asyncio as _asyncio

    from conduit_core.services import webhook_sender

    started = _asyncio.Event()
    finished = _asyncio.Event()

    async def slow(event, payload, **kw):
        started.set()
        await _asyncio.sleep(0.5)
        finished.set()

    monkeypatch.setattr(webhook_sender, "deliver", slow)

    task = webhook_sender.fire("test.event", {"hello": "world"})
    # fire() returned synchronously. Give the loop a chance to start the task.
    await _asyncio.sleep(0)
    assert started.is_set() or task in webhook_sender._pending_tasks
    assert not finished.is_set()
    await webhook_sender.flush(timeout=2.0)
    assert finished.is_set()
