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

`safe_get(url, ...)` runs the guard, then fetches with redirects DISABLED
(a 30x to an internal address would bypass the pre-flight check) and a
hard cap on the response body size.

Residual risk: there is a TOCTOU window between DNS resolution in
`assert_safe_url` and the connection httpx makes — a DNS-rebinding attacker
who flips the record to a private IP in between could still slip through.
Closing that fully requires pinning the resolved IP onto the connection
(custom transport / resolver). See follow-ups.
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
    return (
        ip.is_private  # RFC1918 10/8, 172.16/12, 192.168/16 + IPv6 ULA fc00::/7
        or ip.is_loopback  # 127/8, ::1
        or ip.is_link_local  # 169.254/16 (covers 169.254.169.254), fe80::/10
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified  # 0.0.0.0, ::
    )


def assert_safe_url(url: str) -> None:
    """Raise InvalidInput unless `url` is an https URL whose host resolves
    only to public, routable IP addresses.

    All addresses returned by DNS are checked; if any one is unsafe the URL
    is rejected, so a split-horizon / dual-record host cannot smuggle a
    private target past us.
    """
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise InvalidInput(f"Refusing non-https URL: {url!r}")
    host = parts.hostname
    if not host:
        raise InvalidInput(f"URL has no host: {url!r}")

    # If the host is already a literal IP, classify it directly — getaddrinfo
    # would happily echo it back but being explicit is clearer.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _is_unsafe_ip(literal):
            raise InvalidInput(f"Refusing URL pointing at non-public address {host!r}")
        return

    try:
        infos = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise InvalidInput(f"Could not resolve host {host!r}: {e}") from e
    if not infos:
        raise InvalidInput(f"Host {host!r} did not resolve to any address")

    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
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


async def safe_get(
    url: str,
    *,
    params: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = MAX_RESPONSE_BYTES,
    client: httpx.AsyncClient | None = None,
) -> httpx.Response:
    """SSRF-safe GET.

    Validates `url` with `assert_safe_url`, fetches with redirects DISABLED
    (so a 30x cannot bounce us onto an internal address after the check), and
    rejects responses larger than `max_bytes`.

    Pass `client` to reuse an existing session; if omitted a short-lived one
    is created. `follow_redirects` is forced False regardless of the client's
    own default.
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

    if client is not None:
        return await _do(client)
    async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as c:
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

    Validates `url` with `assert_safe_url` then POSTs with redirects DISABLED.
    A `client` may be supplied to reuse a session; `follow_redirects` is
    forced False.
    """
    assert_safe_url(url)
    if client is not None:
        return await client.post(
            url, content=content, headers=headers, follow_redirects=False, timeout=timeout
        )
    async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as c:
        return await c.post(
            url, content=content, headers=headers, follow_redirects=False, timeout=timeout
        )
