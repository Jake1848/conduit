"""HTTP middleware — rate limiter + request logger.

The rate limiter is an in-process token bucket. Per API key when an Authorization
header is present, per client IP otherwise. The store is a plain dict keyed by
those identifiers, so it is **per-uvicorn-worker** — running multiple workers
divides the effective limit by the worker count and lets a smart attacker land
N×limit requests by hashing onto different workers. For a single-worker
deployment behind nginx this is fine; for multi-worker, put a Redis-backed
limiter in front of uvicorn (haproxy, nginx limit_req, or an APIM).

Health checks (/v1/health) bypass the limiter so liveness probes never get
429'd. Everything else passes through it.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .config import Settings

log = structlog.get_logger(__name__)

_HEALTH_PATHS = {"/v1/health"}


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class TokenBucket:
    """Per-key token bucket. Lock-protected for asyncio fairness."""

    def __init__(self, rate_per_minute: int, burst: int) -> None:
        self.rate = rate_per_minute / 60.0  # tokens per second
        self.burst = burst
        self._buckets: dict[str, _Bucket] = {}
        self._lock = asyncio.Lock()

    async def take(self, key: str) -> tuple[bool, int]:
        """Try to consume one token. Returns (allowed, retry_after_seconds)."""
        async with self._lock:
            now = time.monotonic()
            b = self._buckets.get(key)
            if b is None:
                b = _Bucket(tokens=float(self.burst), last_refill=now)
                self._buckets[key] = b
            elapsed = now - b.last_refill
            b.tokens = min(self.burst, b.tokens + elapsed * self.rate)
            b.last_refill = now
            if b.tokens >= 1.0:
                b.tokens -= 1.0
                return True, 0
            # Time until we'll have 1 token.
            seconds = max(1, int((1.0 - b.tokens) / self.rate) + 1)
            return False, seconds

    def reset(self) -> None:
        self._buckets.clear()


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self._enabled = settings.rate_limit_per_minute > 0
        self._bucket = TokenBucket(
            rate_per_minute=settings.rate_limit_per_minute,
            burst=settings.rate_limit_burst,
        )

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if not self._enabled or request.url.path in _HEALTH_PATHS:
            return await call_next(request)

        key = self._identify(request)
        allowed, retry_after = await self._bucket.take(key)
        if not allowed:
            log.warning("rate_limited", key=_redact(key), path=request.url.path)
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                # Nest under `detail` to match every other error envelope in the API
                # (the ConduitError handler returns {"detail": {...}}). SDK parsers read
                # the code from body.detail.code, so a flat body would surface as a
                # generic ConduitError instead of the typed RateLimited.
                content={
                    "detail": {
                        "error": "rate_limited",
                        "code": "RATE_LIMITED",
                        "detail": (
                            "Too many requests. Slow down and retry after "
                            f"{retry_after} seconds."
                        ),
                        "retry_after": retry_after,
                    }
                },
            )
        return await call_next(request)

    @staticmethod
    def _identify(request: Request) -> str:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            if token:
                # Use a prefix of the raw key — we don't want the full secret in
                # any in-memory dump but we need enough to distinguish keys.
                return "key:" + token[:16]
        # Prefer the X-Forwarded-For first IP if present (we sit behind nginx).
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return "ip:" + xff.split(",")[0].strip()
        client = request.client
        return "ip:" + (client.host if client else "unknown")


def _redact(key: str) -> str:
    # Don't print the bucket key verbatim to logs — it can be a key fragment.
    if key.startswith("key:"):
        return "key:****" + key[-4:]
    return key
