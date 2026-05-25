"""Webhook delivery — HMAC-signed POSTs with bounded retries."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db.models import Webhook

log = structlog.get_logger(__name__)


def sign(secret: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


async def deliver(
    session: AsyncSession,
    event: str,
    payload: dict[str, Any],
    max_retries: int | None = None,
    timeout: float | None = None,
) -> None:
    """Fan out an event to all active webhooks subscribed to it."""
    settings = get_settings()
    max_retries = max_retries if max_retries is not None else settings.webhook_max_retries
    timeout = timeout if timeout is not None else float(settings.webhook_timeout_seconds)

    rows = (await session.execute(select(Webhook).where(Webhook.active.is_(True)))).scalars().all()
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
