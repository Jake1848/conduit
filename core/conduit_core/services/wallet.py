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


def _normalize_host(host: str) -> str:
    """Lower-case and strip a trailing root dot for comparison.

    ``Example.COM`` and ``example.com.`` (the FQDN root form) are the same
    host; normalise both so the comparison below isn't fooled by case or a
    trailing dot.
    """
    return host.lower().rstrip(".")


# A small, dependency-free set of MULTI-LABEL public suffixes. These are the
# cases where the naive "last two labels" heuristic is wrong: domains under
# these suffixes are independently registered/owned, so two hosts that merely
# share the suffix (e.g. a.github.io vs b.github.io) are NOT the same party.
#
# This is deliberately NOT a full Public Suffix List — that would be a large
# data dependency. It covers the common evasion targets (ccTLD second levels
# like co.uk, GitHub Pages, S3, common cloud/app hosting) and is layered as
# defense-in-depth ON TOP of the SSRF IP guard, so a miss here cannot by
# itself reach a private address. A leading "*." entry matches any single
# label in that position (e.g. *.amazonaws.com covers s3/eu-west-1.amazonaws…).
_MULTI_LABEL_PUBLIC_SUFFIXES: frozenset[str] = frozenset(
    {
        # ccTLD second-level registries (RFC-style "co.uk" family).
        "co.uk", "org.uk", "gov.uk", "ac.uk", "me.uk", "ltd.uk", "plc.uk",
        "com.au", "net.au", "org.au", "gov.au", "edu.au",
        "co.nz", "net.nz", "org.nz",
        "co.jp", "or.jp", "ne.jp", "ac.jp", "go.jp",
        "co.in", "net.in", "org.in",
        "com.br", "net.br", "org.br",
        "co.za", "org.za",
        "com.cn", "net.cn", "org.cn", "gov.cn",
        "co.kr", "or.kr",
        # Shared app/object-hosting suffixes (each subdomain is a tenant).
        "github.io", "githubusercontent.com",
        "s3.amazonaws.com", "s3.dualstack.us-east-1.amazonaws.com",
        "herokuapp.com", "herokudns.com",
        "appspot.com", "web.app", "firebaseapp.com",
        "cloudfront.net", "azurewebsites.net", "azureedge.net",
        "vercel.app", "netlify.app", "pages.dev", "workers.dev",
        "blob.core.windows.net",
    }
)

# Suffix patterns with a single-label wildcard in the FIRST position. Matched
# against the LAST N labels of a host (N = number of pattern labels).
_WILDCARD_PUBLIC_SUFFIXES: tuple[str, ...] = (
    "*.amazonaws.com",  # s3.amazonaws.com, eu-west-1.compute.amazonaws.com, …
    "*.compute.amazonaws.com",
    "*.r2.cloudflarestorage.com",
)


def _registrable_domain(host: str) -> str:
    """Public-suffix-aware eTLD+1 of a (normalised) hostname.

    Returns the public suffix plus ONE more label — the registrable domain,
    i.e. the smallest unit a single party can register. This replaces the old
    "last two labels" heuristic, which wrongly collapsed independently-owned
    hosts that share a multi-label public suffix (foo.co.uk vs bar.co.uk,
    a.github.io vs b.github.io, x.s3.amazonaws.com vs y.s3.amazonaws.com) into
    the same "domain" — letting an attacker on a shared suffix pass the
    same-domain callback check.

    For a host that IS exactly a public suffix (e.g. ``github.io`` itself) the
    whole host is returned, so it can never tie to another registrable domain.
    """
    host = _normalize_host(host)
    labels = host.strip(".").split(".")
    if len(labels) <= 1:
        return host

    # Longest matching public suffix wins (exact set entries, then wildcards).
    suffix_len = 1  # default eTLD is the single rightmost label (e.g. "com")
    for n in range(len(labels) - 1, 0, -1):
        candidate = ".".join(labels[-n:])
        if candidate in _MULTI_LABEL_PUBLIC_SUFFIXES or _matches_wildcard_suffix(labels[-n:]):
            suffix_len = n
            break

    # registrable domain = public suffix + one more label, if one exists.
    if len(labels) > suffix_len:
        return ".".join(labels[-(suffix_len + 1):])
    # Host is itself exactly a public suffix — return it unchanged.
    return host


def _matches_wildcard_suffix(tail_labels: list[str]) -> bool:
    """True if `tail_labels` (the last N labels of a host) matches one of the
    single-label-wildcard public-suffix patterns of the same length."""
    n = len(tail_labels)
    for pattern in _WILDCARD_PUBLIC_SUFFIXES:
        plabels = pattern.split(".")
        if len(plabels) != n:
            continue
        ok = True
        for pl, hl in zip(plabels, tail_labels, strict=True):
            if pl == "*":
                continue
            if pl != hl:
                ok = False
                break
        if ok:
            return True
    return False


def _same_callback_domain(callback_host: str, address_host: str) -> bool:
    """Defense-in-depth: the LNURL `callback` host must share the registrable
    domain of the lightning-address host.

    The callback is RESPONSE-supplied (a malicious LNURL server controls it),
    so even though the SSRF IP guard already blocks private targets, we also
    require the callback to stay within the same registrable domain so it can't
    be aimed at an unrelated party that merely shares a public suffix.
    Subdomains of the SAME registrable domain (e.g. pay.example.com for
    example.com) are allowed, since that's a normal LNURL-pay deployment.
    """
    return _registrable_domain(callback_host) == _registrable_domain(address_host)


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
        # private/loopback/link-local/metadata addresses. safe_get validates up
        # front AND pins the connection to a validated IP (see safe_http), so a
        # DNS-rebinding flip can't slip a private IP past the check. The passed
        # `client` is accepted for compatibility but safe_get uses its own
        # pinning transport.
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
        if not _same_callback_domain(cb_host, host):
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
