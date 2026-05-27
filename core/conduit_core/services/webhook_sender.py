"""Webhook delivery — HMAC-signed POSTs with bounded retries.

`fire(event, payload)` schedules delivery as a background asyncio.Task and
returns immediately. This is the entry point callers should use — if a
webhook receiver is slow or down, the originating request (a payment,
invoice settlement) must not block on it. A failed delivery is logged but
NEVER turns a successful payment into a 500 to the client; that's how
network blips become double-charges.

`flush(timeout)` awaits all in-flight delivery tasks — used by tests and
by graceful shutdown to drain pending webhooks before tearing down the
process.

`deliver(...)` is the underlying coroutine; it opens its own DB session
because the request-scoped session is gone by the time the background
task runs.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from collections.abc import Coroutine
from typing import Any

import httpx
import structlog
from sqlalchemy import select

from ..config import get_settings
from ..db.models import Webhook

log = structlog.get_logger(__name__)

# Tracked so tests + graceful shutdown can drain.
_pending_tasks: set[asyncio.Task] = set()


def sign(secret: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


async def deliver(
    event: str,
    payload: dict[str, Any],
    *,
    max_retries: int | None = None,
    timeout: float | None = None,
) -> None:
    """Fan out an event to all active webhooks subscribed to it.

    Opens its own DB session — the caller's request-scoped session may be
    closed by the time this runs as a background task.
    """
    from ..db import SessionLocal  # local import to avoid circulars at module import

    settings = get_settings()
    max_retries = max_retries if max_retries is not None else settings.webhook_max_retries
    timeout = timeout if timeout is not None else float(settings.webhook_timeout_seconds)

    async with SessionLocal() as session:
        rows = (
            await session.execute(select(Webhook).where(Webhook.active.is_(True)))
        ).scalars().all()

    if not rows:
        return

    body_bytes = json.dumps(
        {"event": event, "data": payload, "ts": int(time.time())},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    server_signature = sign(settings.api_secret_key, body_bytes)

    async with httpx.AsyncClient(timeout=timeout) as client:
        tasks = []
        for wh in rows:
            try:
                events = json.loads(wh.events)
            except json.JSONDecodeError:
                continue
            if event not in events and "*" not in events:
                continue
            tasks.append(
                _deliver_one(client, wh, body_bytes, event, max_retries, server_signature)
            )
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def fire(event: str, payload: dict[str, Any]) -> asyncio.Task:
    """Schedule webhook delivery in the background and return immediately.

    Failures inside the delivery do NOT propagate to the caller — the only
    visible effect on the caller is a fast return. Use `flush()` in tests
    (and at shutdown) to await all in-flight deliveries.
    """
    return _spawn(deliver(event, payload))


def _spawn(coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)
    task.add_done_callback(_log_task_errors)
    return task


def _log_task_errors(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.exception(
            "webhook_task_unhandled_error",
            error=str(exc),
            exc_info=(type(exc), exc, exc.__traceback__),
        )


async def flush(timeout: float = 30.0) -> None:
    """Await all in-flight webhook deliveries.

    Tests must call this before asserting on a captured `delivered` list,
    since `fire()` returns before the underlying task runs.
    """
    while _pending_tasks:
        pending = list(_pending_tasks)
        done, _ = await asyncio.wait(pending, timeout=timeout)
        # Discard completed tasks so the next iteration only sees newly-added ones.
        for t in done:
            _pending_tasks.discard(t)
        if not done:
            # Timeout — give up rather than spinning forever.
            log.warning(
                "webhook_flush_timeout", pending=len(_pending_tasks), timeout=timeout
            )
            return


async def _deliver_one(
    client: httpx.AsyncClient,
    wh: Webhook,
    body: bytes,
    event: str,
    max_retries: int,
    server_signature: str,
) -> None:
    headers = {
        "Content-Type": "application/json",
        "X-Conduit-Signature": sign(wh.secret, body),
        "X-Conduit-Server-Signature": server_signature,
        "X-Conduit-Event": event,
        "X-Conduit-Webhook-Id": wh.id,
    }
    delay = 1.0
    for attempt in range(max_retries):
        try:
            r = await client.post(wh.url, content=body, headers=headers)
            if r.status_code < 400:
                log.info(
                    "webhook_delivered",
                    webhook_id=wh.id,
                    event=event,
                    status=r.status_code,
                    attempt=attempt + 1,
                )
                return
            log.warning(
                "webhook_non2xx",
                webhook_id=wh.id,
                event=event,
                status=r.status_code,
                attempt=attempt + 1,
            )
        except httpx.HTTPError as e:
            log.warning(
                "webhook_delivery_error",
                webhook_id=wh.id,
                event=event,
                error=str(e),
                attempt=attempt + 1,
            )
        await asyncio.sleep(delay)
        delay = min(delay * 2, 60)
    log.error("webhook_giving_up", webhook_id=wh.id, event=event, attempts=max_retries)
