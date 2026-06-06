"""v0.7.0 hardening: request id, readiness probe, XFF identity, idempotency prune."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from conduit_core.db.models import IdempotencyRecord
from conduit_core.middleware import RateLimitMiddleware

# ---------- request id ----------


class _Headers(dict):
    def get(self, key, default=""):  # mimic Starlette's case-insensitive headers
        return super().get(key.lower(), default)


class _FakeRequest:
    def __init__(self, headers: dict, client_host: str | None = None):
        self.headers = _Headers({k.lower(): v for k, v in headers.items()})
        self.client = type("C", (), {"host": client_host})() if client_host else None


@pytest.mark.asyncio
async def test_request_id_generated_and_returned(client):
    r = await client.get("/v1/health")
    assert r.status_code == 200
    rid = r.headers.get("X-Request-ID")
    assert rid and rid.startswith("req_")


@pytest.mark.asyncio
async def test_request_id_echoed_when_supplied(client):
    r = await client.get("/v1/health", headers={"X-Request-ID": "trace-abc-123"})
    assert r.headers.get("X-Request-ID") == "trace-abc-123"


@pytest.mark.asyncio
async def test_request_id_rejects_garbage(client):
    # Whitespace-containing ids (log-injection risk) are replaced with a fresh one.
    r = await client.get("/v1/health", headers={"X-Request-ID": "bad id\nwith newline"})
    rid = r.headers.get("X-Request-ID")
    assert rid.startswith("req_")


# ---------- readiness ----------


@pytest.mark.asyncio
async def test_ready_reports_components(client):
    r = await client.get("/v1/health/ready")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["components"]["database"]["ok"] is True
    # LND is mocked in tests → reachable.
    assert body["components"]["lnd"]["ok"] is True


# ---------- XFF identity (rate-limit bucket key) ----------


def test_identify_uses_rightmost_xff():
    # Client forges a fake left-most entry; nginx appends the real peer on the right.
    req = _FakeRequest({"X-Forwarded-For": "1.2.3.4, 203.0.113.9"})
    assert RateLimitMiddleware._identify(req) == "ip:203.0.113.9"


def test_identify_single_xff():
    req = _FakeRequest({"X-Forwarded-For": "203.0.113.9"})
    assert RateLimitMiddleware._identify(req) == "ip:203.0.113.9"


def test_identify_falls_back_to_client_host():
    req = _FakeRequest({}, client_host="198.51.100.5")
    assert RateLimitMiddleware._identify(req) == "ip:198.51.100.5"


def test_identify_prefers_api_key():
    req = _FakeRequest({"Authorization": "Bearer ck_test_abcdefghijklmnopqrstuvwxyz"})
    assert RateLimitMiddleware._identify(req) == "key:ck_test_abcdefgh"  # 16-char prefix


# ---------- idempotency retention prune ----------


@pytest.mark.asyncio
async def test_pruner_deletes_old_keeps_recent(client):
    from conduit_core.db.database import SessionLocal
    from conduit_core.services.maintenance import IdempotencyPruner

    # Create two real idempotency records via actual payments (valid FK to api_keys).
    r = await client.post("/v1/agents", json={"name": "prune-agent"})
    agent_id = r.json()["id"]
    await client.post(f"/v1/agents/{agent_id}/credit", json={"sats": 10_000, "reason": "t"})

    base = {"agent_id": agent_id, "dest_pubkey": "02" + "ab" * 32, "sats": 100}
    await client.post("/v1/payments/send", json=base, headers={"Idempotency-Key": "old-key"})
    await client.post("/v1/payments/send", json=base, headers={"Idempotency-Key": "new-key"})

    # Backdate the "old-key" record well past the retention window.
    async with SessionLocal() as s:
        await s.execute(
            update(IdempotencyRecord)
            .where(IdempotencyRecord.key == "old-key")
            .values(created_at=datetime.now(UTC) - timedelta(hours=100))
        )
        await s.commit()

    pruner = IdempotencyPruner(SessionLocal, retention_hours=72, interval_seconds=3600)
    deleted = await pruner.prune()
    assert deleted == 1

    async with SessionLocal() as s:
        keys = (await s.execute(select(IdempotencyRecord.key))).scalars().all()
        total = (await s.execute(select(func.count()).select_from(IdempotencyRecord))).scalar()
    assert "old-key" not in keys
    assert "new-key" in keys
    assert total == 1
