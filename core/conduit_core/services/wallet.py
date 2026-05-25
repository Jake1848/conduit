"""Wallet/address resolution.

Conduit uses Lightning Addresses for `name@host` payments. The flow:
  1. `name@host` → GET `https://host/.well-known/lnurlp/name`
  2. Parse the LNURL-pay metadata (min/max sats)
  3. POST/GET the `callback` with `amount=msat` → receive a BOLT11 invoice
  4. Pay the invoice via LND
"""

from __future__ import annotations

import httpx
import structlog

from ..errors import InvalidInput, PaymentFailed

log = structlog.get_logger(__name__)


def is_lightning_address(value: str) -> bool:
    if not value or "@" not in value:
        return False
    name, _, host = value.partition("@")
    return bool(name) and "." in host


def is_bolt11(value: str) -> bool:
    return value.lower().startswith(("lnbc", "lntb", "lnbcrt", "lntbs"))


async def resolve_lightning_address_to_invoice(address: str, sats: int, memo: str | None) -> str:
    """Given `name@host` + sats, fetch a BOLT11 invoice via LNURL-pay."""
    if not is_lightning_address(address):
        raise InvalidInput(f"Not a Lightning address: {address}")
    name, _, host = address.partition("@")
    url = f"https://{host}/.well-known/lnurlp/{name}"
    msat = sats * 1000
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(url)
            r.raise_for_status()
            params = r.json()
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
        cb_params: dict[str, str] = {"amount": str(msat)}
        if memo and params.get("commentAllowed", 0) >= len(memo):
            cb_params["comment"] = memo
        try:
            r2 = await client.get(callback, params=cb_params)
            r2.raise_for_status()
            payload = r2.json()
        except httpx.HTTPError as e:
            raise PaymentFailed(f"LNURL-pay callback failed for {address}: {e}") from e
        if payload.get("status") == "ERROR":
            raise PaymentFailed(payload.get("reason", "LNURL-pay callback returned ERROR"))
        invoice = payload.get("pr")
        if not invoice:
            raise PaymentFailed(f"LNURL-pay callback returned no invoice for {address}")
        return invoice
