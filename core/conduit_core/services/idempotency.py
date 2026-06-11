"""Idempotency layer for POST endpoints that move money.

Pattern: clients send `Idempotency-Key: <opaque>` on retries. The first
request runs normally; subsequent requests with the same key return the
cached response WITHOUT re-executing — even if the cached response was a
4xx/5xx. This is what kills the network-blip-double-charge vector.

Scoping: the key is OPERATOR-WIDE — unique on `key` alone, across every API
key the operator holds. A retry that goes out under a different key (key
rotation, a second worker) still dedupes against the original instead of
double-charging. `api_key_id` is recorded for audit but is not part of scope.

Conflict handling: if the same key is reused with a DIFFERENT request
body, we refuse with 409. We never return a cached response for a request
that doesn't match what was originally cached — that would be a worse bug.

Concurrency (v2 — reservation): we RESERVE the key by inserting a `pending`
record (response_status == 0 sentinel) BEFORE executing. The unique `key`
constraint is enforced by Postgres across ALL workers/processes, so a second
truly-concurrent request loses the insert race and is told the key is already
in flight (409) instead of executing a second payment. The winner runs the
payment and then UPDATEs the reservation with the real response. Sequential
retries (network blip → SDK backs off → retries) still get the cached response.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..db.models import IdempotencyRecord
from ..errors import IdempotencyConflict
from .ids import idempotency_id

MAX_KEY_LENGTH = 200
_PENDING = 0  # response_status sentinel for an in-flight reservation (never a real HTTP status)


@dataclass(frozen=True)
class CachedResponse:
    status_code: int
    body: dict[str, Any]


@dataclass(frozen=True)
class ReserveOutcome:
    """Result of trying to reserve an idempotency key."""

    reserved: bool = False  # we won — caller should execute then finalize()
    in_progress: bool = False  # a concurrent request holds the key, still running
    cached: CachedResponse | None = None  # a completed record exists — return it


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


def _decode(rec: IdempotencyRecord) -> CachedResponse | None:
    try:
        body = json.loads(rec.response_body)
    except (json.JSONDecodeError, TypeError):
        return None
    return CachedResponse(status_code=rec.response_status, body=body)


async def reserve(
    api_key_id_value: str, key: str, request_hash: str
) -> ReserveOutcome:
    """Atomically claim `key` (operator-wide) before executing the payment.

    Uses its OWN short-lived session (durable, independent of the route session
    which a failed payment may roll back). Returns:
      - reserved=True  → we won the race; execute then call finalize().
      - in_progress=True → a concurrent request holds the key and hasn't finished.
      - cached=<resp>  → a completed record exists; return it.
    Raises IdempotencyConflict (409) if the key was used with a different body.
    """
    from ..db import SessionLocal  # local import to avoid circulars

    async with SessionLocal() as fresh:
        fresh.add(
            IdempotencyRecord(
                id=idempotency_id(),
                api_key_id=api_key_id_value,
                key=key,
                request_hash=request_hash,
                response_status=_PENDING,
                response_body="",
            )
        )
        try:
            await fresh.commit()
            return ReserveOutcome(reserved=True)
        except IntegrityError:
            await fresh.rollback()

    # Someone already holds `key` (any of the operator's API keys) — inspect it.
    async with SessionLocal() as fresh:
        rec = (
            await fresh.execute(
                select(IdempotencyRecord).where(IdempotencyRecord.key == key)
            )
        ).scalar_one_or_none()
        if rec is None:
            # Vanished between our failed insert and this read (e.g. pruned).
            # Treat as in-progress so we never double-execute.
            return ReserveOutcome(in_progress=True)
        if rec.request_hash != request_hash:
            raise IdempotencyConflict(
                f"Idempotency-Key {key!r} was previously used with a different "
                "request body. Use a fresh key for this request."
            )
        if rec.response_status == _PENDING:
            return ReserveOutcome(in_progress=True)
        cached = _decode(rec)
        if cached is None:
            return ReserveOutcome(in_progress=True)
        return ReserveOutcome(cached=cached)


async def finalize(
    api_key_id_value: str,
    key: str,
    request_hash: str,
    *,
    status_code: int,
    body: dict[str, Any],
) -> None:
    """Write the real response onto the reserved row (UPDATE), so retries get
    the cached outcome. Best-effort: if the reservation vanished, insert fresh."""
    from ..db import SessionLocal

    body_json = json.dumps(body, default=str, separators=(",", ":"))
    async with SessionLocal() as fresh:
        rec = (
            await fresh.execute(
                select(IdempotencyRecord).where(IdempotencyRecord.key == key)
            )
        ).scalar_one_or_none()
        if rec is None:
            fresh.add(
                IdempotencyRecord(
                    id=idempotency_id(),
                    api_key_id=api_key_id_value,
                    key=key,
                    request_hash=request_hash,
                    response_status=status_code,
                    response_body=body_json,
                )
            )
        else:
            rec.response_status = status_code
            rec.response_body = body_json
        try:
            await fresh.commit()
        except IntegrityError:
            await fresh.rollback()
