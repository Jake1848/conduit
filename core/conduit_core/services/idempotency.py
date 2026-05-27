"""Idempotency layer for POST endpoints that move money.

Pattern: clients send `Idempotency-Key: <opaque>` on retries. The first
request runs normally; subsequent requests with the same key return the
cached response WITHOUT re-executing — even if the cached response was a
4xx/5xx. This is what kills the network-blip-double-charge vector.

Scoping: the key is namespaced to the API key that sent it, so two
different agents can each use "abc123" without colliding.

Conflict handling: if the same key is reused with a DIFFERENT request
body, we refuse with 409. We never return a cached response for a request
that doesn't match what was originally cached — that would be a worse bug.

Concurrency: v1 does not protect against two truly concurrent requests
with the same key (both miss the cache, both execute, second store
collides). The unique constraint will reject the duplicate write but the
duplicate payment will have happened. Sequential retries (the common
case — network blip, SDK backs off, retries) are fully covered.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import IdempotencyRecord
from ..errors import IdempotencyConflict
from .ids import idempotency_id

MAX_KEY_LENGTH = 200


@dataclass(frozen=True)
class CachedResponse:
    status_code: int
    body: dict[str, Any]


def hash_payload(body: BaseModel | dict[str, Any]) -> str:
    """Canonical sha256 of a request body. Pydantic models are dumped with
    None fields excluded so cosmetic JSON differences (a missing optional
    field vs the same field as null) hash identically."""
    if isinstance(body, BaseModel):
        body = body.model_dump(exclude_none=True, mode="json")
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def validate_key(key: str) -> str:
    key = key.strip()
    if not key:
        raise IdempotencyConflict("Idempotency-Key must be non-empty if provided.")
    if len(key) > MAX_KEY_LENGTH:
        raise IdempotencyConflict(
            f"Idempotency-Key exceeds max length ({MAX_KEY_LENGTH})."
        )
    return key


async def lookup(
    session: AsyncSession, api_key_id_value: str, key: str, request_hash: str
) -> CachedResponse | None:
    """Return cached response if (api_key_id, key) exists.

    Raises IdempotencyConflict if a cached record exists but its
    request_hash differs — never return a cached response for a different
    request.
    """
    row = await session.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.api_key_id == api_key_id_value,
            IdempotencyRecord.key == key,
        )
    )
    rec = row.scalar_one_or_none()
    if rec is None:
        return None
    if rec.request_hash != request_hash:
        raise IdempotencyConflict(
            f"Idempotency-Key {key!r} was previously used with a different "
            "request body. Use a fresh key for this request."
        )
    try:
        body = json.loads(rec.response_body)
    except json.JSONDecodeError:
        return None
    return CachedResponse(status_code=rec.response_status, body=body)


async def store(
    session: AsyncSession,
    api_key_id_value: str,
    key: str,
    request_hash: str,
    *,
    status_code: int,
    body: dict[str, Any],
) -> None:
    """Persist a response under (api_key_id, key).

    Uses its OWN session — we may be called from a route whose request
    session was rolled back by a failed payment. Sharing that session
    risks SQLAlchemy state errors. A fresh session also means the store
    is durable independent of whatever the route does next.

    On unique-constraint collision (concurrent insert) we swallow — the
    other side already wrote and the next lookup will hit that record.
    """
    from ..db import SessionLocal  # local import to avoid circulars

    rec_id = idempotency_id()
    body_json = json.dumps(body, default=str, separators=(",", ":"))

    async with SessionLocal() as fresh:
        fresh.add(
            IdempotencyRecord(
                id=rec_id,
                api_key_id=api_key_id_value,
                key=key,
                request_hash=request_hash,
                response_status=status_code,
                response_body=body_json,
            )
        )
        try:
            await fresh.commit()
        except IntegrityError:
            await fresh.rollback()
            return
