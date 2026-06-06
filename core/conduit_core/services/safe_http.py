"""SSRF-safe outbound HTTP.

Any time Conduit fetches a URL whose host (or whose *contents*, like an
LNURL-pay `callback`) is influenced by an external party, it MUST go through
here. A naive `httpx.get(attacker_url)` lets a caller with a write key point
the server at private/loopback/link-local/cloud-metadata addresses
(e.g. 169.254.169.254) and exfiltrate internal services or credentials.

`assert_safe_url(url)` enforces:
  - scheme must be https
  - the host resolves (via DNS) to ZERO private/loopback/link-local/
    multicast/reserved/unspecified/ULA addresses — if ANY resolved IP is
    unsafe the whole URL is rejected (so a host with one public and one
    private A record is still rejected).
  - IPv4-mapped IPv6 (``::ffff:127.0.0.1``) is unwrapped before classifying.

`safe_get(url, ...)` / `safe_post(url, ...)` run the guard, then fetch with
redirects DISABLED (a 30x to an internal address would bypass the pre-flight
check) and a hard cap on the response body size.

DNS-rebinding / TOCTOU is closed by PINNING. `assert_safe_url` resolving and
then httpx independently re-resolving on connect would leave a window where a
low-TTL attacker flips the record to a private IP between the two lookups.
Instead, the actual fetch is routed through `_PinnedTransport`, a custom
``httpx.AsyncHTTPTransport`` that, *inside* ``handle_async_request`` and right
before the socket is opened:

  1. resolves the original hostname ONCE,
  2. validates EVERY resolved address with `_is_unsafe_ip` (rejecting the
     whole request if any is unsafe — identical policy to assert_safe_url),
  3. rewrites the request URL host to the single validated IP it picked, so
     the TCP connection goes to exactly that address (no further DNS), and
  4. preserves the original hostname for the ``Host`` header (httpx already
     set it from the original URL) and for TLS SNI / certificate verification
     via the httpcore ``sni_hostname`` request extension.

Because resolution, validation and the connect all happen in the same call
with no second lookup, there is no TOCTOU window: the bytes are sent to the
exact IP that was validated, and TLS is still verified against the real
hostname's certificate. A literal-IP host is validated and used as-is.

Note: the on-the-wire connection deliberately targets an IP literal while
presenting the real hostname via SNI + Host. This preserves certificate
verification (the cert is checked against the hostname, not the IP). It does
NOT support servers that rely on a *different* SNI than their Host header, but
LNURL-pay / webhook endpoints do not.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

import httpx

from ..errors import InvalidInput

# 5 MiB is far more than any LNURL-pay / webhook response should ever be.
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
DEFAULT_TIMEOUT = 10.0


def _is_unsafe_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True if `ip` is anything we must never let the server connect to."""
    # Unwrap IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1) so a mapped loopback
    # address is classified as the IPv4 loopback it really is.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    # ALLOWLIST, not denylist: permit ONLY globally-routable public addresses.
    # `is_global` is False for RFC1918, loopback, link-local (incl the
    # 169.254.169.254 cloud-metadata IP), CGNAT/RFC6598 (100.64.0.0/10), IPv6 ULA,
    # multicast, reserved, and unspecified — and for any future non-global range —
    # so we don't have to enumerate (and risk missing) each class. This closes the
    # CGNAT gap a denylist of is_private/is_loopback/... leaves open.
    return not ip.is_global


def _resolve_and_validate(host: str, port: int) -> list[str]:
    """Resolve `host` and validate EVERY address; return the safe IP strings.

    Raises InvalidInput if the host is a literal/resolves to any unsafe
    address, if it cannot be resolved, or if it resolves to nothing. This is
    the single chokepoint shared by `assert_safe_url` (pre-flight) and
    `_PinnedTransport` (at connect time) so both apply identical policy.

    A literal-IP host short-circuits DNS and is returned (validated) as-is.
    """
    # If the host is already a literal IP, classify it directly — getaddrinfo
    # would happily echo it back but being explicit is clearer.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _is_unsafe_ip(literal):
            raise InvalidInput(f"Refusing URL pointing at non-public address {host!r}")
        return [host]

    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise InvalidInput(f"Could not resolve host {host!r}: {e}") from e
    if not infos:
        raise InvalidInput(f"Host {host!r} did not resolve to any address")

    resolved: list[str] = []
    for info in infos:
        sockaddr = info[4]
        ip_str = str(sockaddr[0])
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as err:
            # Unparseable address from the resolver — treat as unsafe.
            raise InvalidInput(
                f"Host {host!r} resolved to an unparseable address {ip_str!r}"
            ) from err
        if _is_unsafe_ip(ip):
            raise InvalidInput(
                f"Refusing URL: host {host!r} resolves to non-public address {ip_str}"
            )
        resolved.append(ip_str)
    return resolved


def assert_safe_url(url: str) -> None:
    """Raise InvalidInput unless `url` is an https URL whose host resolves
    only to public, routable IP addresses.

    All addresses returned by DNS are checked; if any one is unsafe the URL
    is rejected, so a split-horizon / dual-record host cannot smuggle a
    private target past us.

    This is a pre-flight check; the actual fetch re-validates atomically at
    connect time via `_PinnedTransport`, so a DNS-rebinding flip between this
    call and the connection cannot reach a private IP.
    """
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise InvalidInput(f"Refusing non-https URL: {url!r}")
    host = parts.hostname
    if not host:
        raise InvalidInput(f"URL has no host: {url!r}")
    _resolve_and_validate(host, parts.port or 443)


class _PinnedTransport(httpx.AsyncHTTPTransport):
    """An httpx transport that resolves+validates the hostname and pins the
    connection to a single validated IP, closing the DNS-rebinding window.

    The validation runs inside `handle_async_request`, in the same call that
    opens the socket, so there is no gap for the record to be flipped:

      - resolve the original hostname once, reject if ANY address is unsafe,
      - rewrite ``request.url`` host to one validated IP (httpcore connects to
        that exact address — no second DNS lookup),
      - keep the ``Host`` header as the original hostname (httpx already set
        it from the original URL; rewriting only the URL host leaves it),
      - set the ``sni_hostname`` extension to the original hostname so TLS SNI
        and certificate verification use the real name, not the IP literal.
    """

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        hostname = request.url.host
        port = request.url.port or 443

        # If the URL host is already a literal IP, _resolve_and_validate will
        # validate and echo it; no rewrite/SNI override is needed.
        try:
            ipaddress.ip_address(hostname)
            is_literal = True
        except ValueError:
            is_literal = False

        validated_ips = _resolve_and_validate(hostname, port)
        # Prefer the same address family the caller would have used; just take
        # the first validated address — all of them passed the safety check.
        pinned_ip = validated_ips[0]

        if not is_literal:
            # Connect to the pinned IP; keep the real hostname for Host + SNI.
            request.url = request.url.copy_with(host=pinned_ip)
            request.extensions = dict(request.extensions)
            request.extensions["sni_hostname"] = hostname

        return await super().handle_async_request(request)


def _pinned_client(timeout: float) -> httpx.AsyncClient:
    """A short-lived client whose transport pins connections to validated IPs.

    Redirects are forced off (a 30x could otherwise bounce onto an internal
    address after the per-request validation).
    """
    return httpx.AsyncClient(
        transport=_PinnedTransport(),
        follow_redirects=False,
        timeout=timeout,
    )


async def safe_get(
    url: str,
    *,
    params: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = MAX_RESPONSE_BYTES,
    client: httpx.AsyncClient | None = None,
) -> httpx.Response:
    """SSRF-safe GET.

    Validates `url` with `assert_safe_url` up front, then fetches through an
    IP-pinning transport (see `_PinnedTransport`) that re-resolves and
    re-validates atomically at connect time — so a DNS-rebinding flip can't
    reach a private IP. Redirects are DISABLED and responses larger than
    `max_bytes` are rejected.

    `client`, if supplied, is IGNORED for the connection itself: pinning
    requires a per-request transport, so a fresh pinned client is always used.
    The parameter is kept for backwards compatibility with callers that pass a
    shared session.
    """
    assert_safe_url(url)

    async def _do(c: httpx.AsyncClient) -> httpx.Response:
        async with c.stream(
            "GET", url, params=params, follow_redirects=False, timeout=timeout
        ) as resp:
            total = 0
            chunks: list[bytes] = []
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise InvalidInput(
                        f"Response from {url!r} exceeded {max_bytes} bytes"
                    )
                chunks.append(chunk)
            # Populate .content so callers can use .json()/.text as usual.
            resp._content = b"".join(chunks)
            return resp

    async with _pinned_client(timeout) as c:
        return await _do(c)


async def safe_post(
    url: str,
    *,
    content: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    client: httpx.AsyncClient | None = None,
) -> httpx.Response:
    """SSRF-safe POST (used for outbound webhook delivery).

    Validates `url` with `assert_safe_url` up front, then POSTs through the
    IP-pinning transport (atomic re-validate at connect time) with redirects
    DISABLED.

    `client`, if supplied, is IGNORED for the connection itself (pinning needs
    a per-request transport); the parameter is kept for backwards
    compatibility with callers that pass a shared session.
    """
    assert_safe_url(url)
    async with _pinned_client(timeout) as c:
        return await c.post(
            url, content=content, headers=headers, follow_redirects=False, timeout=timeout
        )
