"""Wallet/address resolution.

Conduit uses Lightning Addresses for `name@host` payments. The flow:
  1. `name@host` → GET `https://host/.well-known/lnurlp/name`
  2. Parse the LNURL-pay metadata (min/max sats)
  3. POST/GET the `callback` with `amount=msat` → receive a BOLT11 invoice
  4. Pay the invoice via LND
"""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx
import structlog

from ..errors import InvalidInput, PaymentFailed
from .safe_http import assert_safe_url, safe_get

log = structlog.get_logger(__name__)


def is_lightning_address(value: str) -> bool:
    if not value or "@" not in value:
        return False
    name, _, host = value.partition("@")
    return bool(name) and "." in host


def is_bolt11(value: str) -> bool:
    return value.lower().startswith(("lnbc", "lntb", "lnbcrt", "lntbs"))


def _registrable_domain(host: str) -> str:
    """Crude eTLD+1: the last two labels of a hostname.

    Used only as a defense-in-depth same-origin check on the LNURL `callback`
    so a payRequest at `name@host` can't redirect the callback fetch at an
    unrelated domain. This is intentionally simple (no public-suffix list); it
    is a hardening check layered on top of the SSRF IP guard, not the primary
    control.
    """
    labels = host.lower().strip(".").split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else host.lower()


async def resolve_lightning_address_to_invoice(address: str, sats: int, memo: str | None) -> str:
    """Given `name@host` + sats, fetch a BOLT11 invoice via LNURL-pay."""
    if not is_lightning_address(address):
        raise InvalidInput(f"Not a Lightning address: {address}")
    name, _, host = address.partition("@")
    url = f"https://{host}/.well-known/lnurlp/{name}"
    msat = sats * 1000
    async with httpx.AsyncClient(follow_redirects=False, timeout=10.0) as client:
        # SSRF guard: `host` is attacker-controllable (it comes straight from the
        # payment request), so the well-known fetch must not be allowed to reach
        # private/loopback/link-local/metadata addresses. assert_safe_url runs
        # inside safe_get; reject before any socket is opened.
        try:
            r = await safe_get(url, client=client)
            r.raise_for_status()
            params = r.json()
        except InvalidInput:
            raise
        except httpx.HTTPError as e:
            raise PaymentFailed(f"LNURL-pay lookup failed for {address}: {e}") from e

        if params.get("tag") != "payRequest":
            raise PaymentFailed(f"LNURL-pay tag invalid for {address}: {params.get('tag')!r}")
        min_sendable = int(params.get("minSendable", 0))
        max_sendable = int(params.get("maxSendable", 0))
        if msat < min_sendable or msat > max_sendable:
            raise PaymentFailed(
                f"{sats} sats outside LNURL-pay bounds "
                f"[{min_sendable // 1000}, {max_sendable // 1000}] for {address}"
            )
        callback = params["callback"]
        # The callback URL is RESPONSE-supplied — a malicious LNURL server could
        # point it at an internal address or an unrelated domain. Require https
        # (assert_safe_url enforces scheme + IP safety) AND, as defense in depth,
        # that it shares the same registrable domain as the lightning-address host.
        try:
            assert_safe_url(callback)
        except InvalidInput as e:
            reason = (
                e.detail.get("detail", str(e.detail))
                if isinstance(e.detail, dict)
                else e.detail
            )
            raise InvalidInput(
                f"LNURL-pay callback for {address} rejected: {reason}"
            ) from e
        cb_host = urlsplit(callback).hostname or ""
        if _registrable_domain(cb_host) != _registrable_domain(host):
            raise InvalidInput(
                f"LNURL-pay callback host {cb_host!r} does not match "
                f"lightning-address domain {host!r}"
            )
        cb_params: dict[str, str] = {"amount": str(msat)}
        if memo and params.get("commentAllowed", 0) >= len(memo):
            cb_params["comment"] = memo
        try:
            r2 = await safe_get(callback, params=cb_params, client=client)
            r2.raise_for_status()
            payload = r2.json()
        except InvalidInput:
            raise
        except httpx.HTTPError as e:
            raise PaymentFailed(f"LNURL-pay callback failed for {address}: {e}") from e
        if payload.get("status") == "ERROR":
            raise PaymentFailed(payload.get("reason", "LNURL-pay callback returned ERROR"))
        invoice = payload.get("pr")
        if not invoice:
            raise PaymentFailed(f"LNURL-pay callback returned no invoice for {address}")
        return invoice
