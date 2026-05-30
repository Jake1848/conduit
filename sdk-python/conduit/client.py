"""HTTP client used by every SDK object.

Adds two production-grade behaviors over a plain httpx client:

  * Automatic retries with exponential backoff on transient failures
    (HTTP 429, 5xx, and network/timeout errors). `Retry-After` is honored
    when the server provides it. 4xx other than 429 are never retried.

  * Idempotency-Key support. Payment methods generate a UUID4 key and pass
    it through; the retry loop reuses the SAME key across attempts so a
    retried payment can never settle twice. See conduit/agent.py.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from .errors import AuthenticationError, ConduitError, raise_for_error

DEFAULT_BASE_URL = "https://api.conduit.energy"
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 1.0  # seconds; delays are base * 2**attempt → 1, 2, 4
# Cap how long we'll honor a server-provided Retry-After so a hostile or
# misconfigured server can't park the client for minutes.
MAX_RETRY_AFTER_SECONDS = 60.0


def _is_retryable_status(status: int) -> bool:
    return status == 429 or 500 <= status < 600


class Conduit:
    """Low-level client. Use the higher-level `Agent` / `Policy` classes for most work."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_base: float = DEFAULT_BACKOFF_BASE,
    ) -> None:
        import conduit as _module

        key = api_key or _module.api_key or os.environ.get("CONDUIT_API_KEY")
        if not key:
            raise AuthenticationError(
                "No API key. Set CONDUIT_API_KEY env var, conduit.api_key, "
                "or pass api_key= to the Agent/Conduit constructor.",
                code="AUTHENTICATION_ERROR",
            )
        self.api_key = key
        self.base_url = (
            base_url
            or _module.base_url
            or os.environ.get("CONDUIT_API_URL")
            or DEFAULT_BASE_URL
        ).rstrip("/")
        self.max_retries = max(0, max_retries)
        self._backoff_base = max(0.0, retry_backoff_base)
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": f"conduit-python/{_version()}",
            },
        )

    # --- low-level HTTP ---

    def get(self, path: str, **kw: Any) -> Any:
        return self._request("GET", path, **kw)

    def post(
        self,
        path: str,
        json: dict | None = None,
        *,
        idempotency_key: str | None = None,
        **kw: Any,
    ) -> Any:
        return self._request("POST", path, json=json, idempotency_key=idempotency_key, **kw)

    def put(self, path: str, json: dict | None = None, **kw: Any) -> Any:
        return self._request("PUT", path, json=json, **kw)

    def delete(self, path: str, **kw: Any) -> Any:
        return self._request("DELETE", path, **kw)

    def _request(
        self,
        method: str,
        path: str,
        *,
        idempotency_key: str | None = None,
        **kw: Any,
    ) -> Any:
        # Build per-request headers ONCE so the idempotency key is identical
        # across every retry attempt — that's what makes retrying a payment safe.
        extra_headers: dict[str, str] = {}
        if idempotency_key:
            extra_headers["Idempotency-Key"] = idempotency_key
        if extra_headers:
            kw = {**kw, "headers": {**kw.get("headers", {}), **extra_headers}}

        attempt = 0
        while True:
            try:
                r = self._client.request(method, path, **kw)
            except httpx.HTTPError as e:
                # Network/timeout error — no response. Safe to retry because
                # payment requests carry an idempotency key.
                if attempt < self.max_retries:
                    self._sleep_backoff(attempt, None)
                    attempt += 1
                    continue
                raise ConduitError(
                    f"Network error contacting {self.base_url}: {e}"
                ) from e

            if r.status_code >= 400:
                if _is_retryable_status(r.status_code) and attempt < self.max_retries:
                    self._sleep_backoff(attempt, r.headers.get("Retry-After"))
                    attempt += 1
                    continue
                try:
                    body = r.json()
                except ValueError:
                    body = {"detail": r.text or f"HTTP {r.status_code}"}
                raise_for_error(r.status_code, body)

            if r.status_code == 204 or not r.content:
                return None
            return r.json()

    def _sleep_backoff(self, attempt: int, retry_after: str | None) -> None:
        delay = self._backoff_base * (2**attempt)
        if retry_after is not None:
            parsed = _parse_retry_after(retry_after)
            if parsed is not None:
                delay = min(parsed, MAX_RETRY_AFTER_SECONDS)
        if delay > 0:
            time.sleep(delay)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Conduit":
        return self

    def __exit__(self, *_) -> None:
        self.close()


def _parse_retry_after(value: str) -> float | None:
    """Parse a Retry-After header into non-negative seconds.

    The Conduit API sends integer seconds; we also tolerate floats. Empty,
    non-numeric (incl. HTTP-date form), and negative values return None so the
    caller falls back to exponential backoff — matching the JS SDK exactly.
    """
    try:
        secs = float(value)
    except (TypeError, ValueError):
        return None
    return secs if secs >= 0 else None


_default: Conduit | None = None


def default_client() -> Conduit:
    global _default
    if _default is None:
        _default = Conduit()
    return _default


def set_default_client(client: Conduit) -> None:
    """Install a pre-configured client as the module default.

    `Agent`/`Policy` use the default client when none is passed explicitly.
    Mirrors the JS SDK's `setDefaultClient` — handy for tests or to inject a
    custom transport/config without threading a client through every call.
    """
    global _default
    _default = client


def _version() -> str:
    try:
        from . import __version__ as v
        return v
    except Exception:
        return "0.0.0"
