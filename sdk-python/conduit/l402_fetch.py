"""Drop-in HTTP middleware that pays L402 paywalls transparently.

Wraps an `httpx` client around the framework-agnostic :class:`conduit.l402.L402Engine`
so existing agent code can call a paywalled (402 / L402) URL and get the body
back, with the Lightning toll paid from a Conduit agent wallet automatically.

    from conduit import Agent
    from conduit.l402 import L402Config
    from conduit.l402_fetch import fetch_with_l402, L402Client

    agent = Agent.create(name="research-bot", daily_limit=50_000)

    # One-shot:
    result = fetch_with_l402("https://api.example.com/paid", agent=agent, sats=210)
    print(result.status, result.body)

    # Reused client (token cache persists across calls — a service-wide token is
    # bought once and reused):
    with L402Client(agent, config=L402Config(max_auto_pay_sats=1000)) as http:
        a = http.fetch("https://api.example.com/v1/a")
        b = http.fetch("https://api.example.com/v1/b")  # reuses the token, no re-pay

Non-402 responses pass through unchanged. All the engine's guards (max-auto-pay
cap, domain allow/deny, re-pay cap) and typed errors apply.
"""

from __future__ import annotations

from typing import Any

import httpx

from .l402 import FetchResult, L402Config, L402Engine, TokenStore, agent_payer


def _httpx_fetcher(client: httpx.Client):
    """Adapt an httpx.Client to the engine's fetcher signature."""

    def _fetch(
        url: str,
        method: str,
        headers: dict[str, str],
        body: str | bytes | None,
    ) -> tuple[int, dict[str, str], str | bytes]:
        content: bytes | None = None
        if body is not None:
            content = body.encode() if isinstance(body, str) else body
        resp = client.request(method, url, headers=headers, content=content)
        return resp.status_code, dict(resp.headers), resp.text

    return _fetch


class L402Client:
    """A reusable L402-paying HTTP client.

    Holds one :class:`L402Engine` (so its token cache persists across calls) and
    one httpx client. Prefer this over :func:`fetch_with_l402` when making
    multiple requests to the same service — the macaroon-scoped token is bought
    once and reused without re-paying.
    """

    def __init__(
        self,
        agent: Any,
        *,
        config: L402Config | None = None,
        store: TokenStore | None = None,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._engine = L402Engine(
            pay_invoice=agent_payer(agent), config=config, store=store
        )
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    def fetch(
        self,
        url: str,
        *,
        sats: int = 1,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | bytes | None = None,
    ) -> FetchResult:
        return self._engine.fetch_paid(
            url,
            fetcher=_httpx_fetcher(self._client),
            sats=sats,
            method=method,
            headers=headers,
            body=body,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> L402Client:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def fetch_with_l402(
    url: str,
    *,
    agent: Any,
    sats: int = 1,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | bytes | None = None,
    config: L402Config | None = None,
    store: TokenStore | None = None,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> FetchResult:
    """Fetch a URL, paying an L402 toll from ``agent`` if the server demands one.

    One-shot convenience — creates a fresh engine each call (no cross-call token
    cache). For repeated calls to the same service use :class:`L402Client`.
    """
    engine = L402Engine(pay_invoice=agent_payer(agent), config=config, store=store)
    own_client = client is None
    http_client = client or httpx.Client(timeout=timeout)
    try:
        return engine.fetch_paid(
            url,
            fetcher=_httpx_fetcher(http_client),
            sats=sats,
            method=method,
            headers=headers,
            body=body,
        )
    finally:
        if own_client:
            http_client.close()


__all__ = ["L402Client", "fetch_with_l402"]
