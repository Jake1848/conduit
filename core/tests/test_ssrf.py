"""SSRF guard tests for Lightning-address / LNURL-pay resolution.

These verify that a caller with a write key can't make the server fetch
private/loopback/link-local/cloud-metadata addresses via either the
`.well-known/lnurlp` lookup or the response-supplied `callback`.

All DNS (socket.getaddrinfo) and HTTP (httpx) are mocked so the suite is
hermetic and never touches the network.
"""

from __future__ import annotations

import socket

import httpx
import pytest

from conduit_core.errors import InvalidInput
from conduit_core.services import safe_http, wallet


def _fake_getaddrinfo_returning(ip: str):
    """Build a getaddrinfo stand-in that always resolves to `ip`."""
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET

    def _fake(host, port, *a, **kw):
        sockaddr = (ip, port or 443, 0, 0) if family == socket.AF_INET6 else (ip, port or 443)
        return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]

    return _fake


# ---------------------------------------------------------------------------
# assert_safe_url
# ---------------------------------------------------------------------------


def test_assert_safe_url_accepts_public_https(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo_returning("93.184.216.34"))
    # Should not raise.
    safe_http.assert_safe_url("https://example.com/.well-known/lnurlp/alice")


def test_assert_safe_url_rejects_non_https(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo_returning("93.184.216.34"))
    with pytest.raises(InvalidInput):
        safe_http.assert_safe_url("http://example.com/.well-known/lnurlp/alice")


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "10.0.0.5",  # RFC1918
        "192.168.1.10",  # RFC1918
        "172.16.0.1",  # RFC1918
        "169.254.169.254",  # link-local / cloud metadata
        "0.0.0.0",  # unspecified
        "::1",  # IPv6 loopback
        "fd00::1",  # IPv6 ULA (private)
        "fe80::1",  # IPv6 link-local
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "::ffff:169.254.169.254",  # IPv4-mapped metadata
    ],
)
def test_assert_safe_url_rejects_non_public(monkeypatch, ip):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo_returning(ip))
    with pytest.raises(InvalidInput):
        safe_http.assert_safe_url(f"https://evil.example/{ip}")


def test_assert_safe_url_rejects_literal_metadata_ip():
    # No DNS needed — the host is a literal IP.
    with pytest.raises(InvalidInput):
        safe_http.assert_safe_url("https://169.254.169.254/latest/meta-data/")


def test_assert_safe_url_rejects_if_any_resolved_ip_unsafe(monkeypatch):
    """A host with one public AND one private record is rejected wholesale."""

    def _fake(host, port, *a, **kw):
        tcp = socket.SOCK_STREAM
        proto = socket.IPPROTO_TCP
        return [
            (socket.AF_INET, tcp, proto, "", ("93.184.216.34", port or 443)),
            (socket.AF_INET, tcp, proto, "", ("127.0.0.1", port or 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", _fake)
    with pytest.raises(InvalidInput):
        safe_http.assert_safe_url("https://split-horizon.example/x")


# ---------------------------------------------------------------------------
# resolve_lightning_address_to_invoice — host (.well-known) is attacker input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "host,ip",
    [
        ("localhost", "127.0.0.1"),
        ("internal.evil", "127.0.0.1"),
        ("ten.evil", "10.1.2.3"),
        ("private.evil", "192.168.0.5"),
        ("metadata.evil", "169.254.169.254"),
    ],
)
async def test_lnurl_lookup_rejects_private_host(monkeypatch, host, ip):
    """A lightning address whose host resolves to a private/loopback/metadata
    IP must be rejected BEFORE any outbound HTTP call."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo_returning(ip))

    # If any HTTP request actually goes out, fail loudly.
    async def _no_http(*a, **kw):
        raise AssertionError("outbound HTTP must not happen for an unsafe host")

    monkeypatch.setattr(httpx.AsyncClient, "stream", _no_http)
    monkeypatch.setattr(httpx.AsyncClient, "get", _no_http)

    with pytest.raises(InvalidInput):
        await wallet.resolve_lightning_address_to_invoice(f"alice@{host}", 100, None)


# ---------------------------------------------------------------------------
# resolve_lightning_address_to_invoice — callback is RESPONSE-supplied
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


@pytest.mark.asyncio
async def test_lnurl_callback_pointing_at_private_ip_is_rejected(monkeypatch):
    """The .well-known host is public, but the returned `callback` points at a
    private IP. The callback fetch must be rejected."""
    # Public host for the lightning address; private for the callback host.
    def _fake_addr(host, port, *a, **kw):
        ip = "127.0.0.1" if host == "callback.evil" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port or 443))]

    monkeypatch.setattr(socket, "getaddrinfo", _fake_addr)

    well_known = {
        "tag": "payRequest",
        "minSendable": 1000,
        "maxSendable": 1_000_000_000,
        "callback": "https://callback.evil/cb",
    }

    async def _fake_safe_get(url, *, params=None, **kw):
        # First (and only legitimate) fetch is the well-known doc.
        assert url == "https://example.com/.well-known/lnurlp/alice"
        return _FakeResponse(well_known)

    monkeypatch.setattr(wallet, "safe_get", _fake_safe_get)

    with pytest.raises(InvalidInput):
        await wallet.resolve_lightning_address_to_invoice("alice@example.com", 100, None)


@pytest.mark.asyncio
async def test_lnurl_callback_cross_domain_is_rejected(monkeypatch):
    """Callback resolves to a public IP but lives on an unrelated registrable
    domain — rejected by the defense-in-depth same-domain check."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo_returning("93.184.216.34"))

    well_known = {
        "tag": "payRequest",
        "minSendable": 1000,
        "maxSendable": 1_000_000_000,
        "callback": "https://attacker-controlled.net/cb",
    }

    async def _fake_safe_get(url, *, params=None, **kw):
        assert url == "https://example.com/.well-known/lnurlp/alice"
        return _FakeResponse(well_known)

    monkeypatch.setattr(wallet, "safe_get", _fake_safe_get)

    with pytest.raises(InvalidInput):
        await wallet.resolve_lightning_address_to_invoice("alice@example.com", 100, None)


@pytest.mark.asyncio
async def test_lnurl_happy_path_same_domain_public_callback(monkeypatch):
    """Sanity: a well-formed public payRequest with a same-domain public
    callback resolves to the invoice (guards don't break the success path)."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo_returning("93.184.216.34"))

    well_known = {
        "tag": "payRequest",
        "minSendable": 1000,
        "maxSendable": 1_000_000_000,
        "callback": "https://pay.example.com/lnurl/cb",
    }
    callback_resp = {"pr": "lnbc1u1pgoodinvoice"}

    calls: list[str] = []

    async def _fake_safe_get(url, *, params=None, **kw):
        calls.append(url)
        if url.endswith("/.well-known/lnurlp/alice"):
            return _FakeResponse(well_known)
        return _FakeResponse(callback_resp)

    monkeypatch.setattr(wallet, "safe_get", _fake_safe_get)

    invoice = await wallet.resolve_lightning_address_to_invoice("alice@example.com", 100, None)
    assert invoice == "lnbc1u1pgoodinvoice"
    assert calls == [
        "https://example.com/.well-known/lnurlp/alice",
        "https://pay.example.com/lnurl/cb",
    ]


# ---------------------------------------------------------------------------
# safe_post (webhook delivery) rejects private targets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safe_post_rejects_private_webhook_target(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo_returning("10.0.0.9"))

    async def _no_post(*a, **kw):
        raise AssertionError("POST must not happen for an unsafe URL")

    monkeypatch.setattr(httpx.AsyncClient, "post", _no_post)

    with pytest.raises(InvalidInput):
        await safe_http.safe_post("https://internal.evil/webhook", content=b"{}")


# ---------------------------------------------------------------------------
# DNS-rebinding / TOCTOU: the fetch must connect ONLY to a validated IP.
#
# These tests intercept at the boundary of the pinning transport: the parent
# `httpx.AsyncHTTPTransport.handle_async_request` is the first thing called
# after `_PinnedTransport` has rewritten the request URL to the pinned IP, so
# `request.url.host` at that point is the exact address the socket will dial.
# We record it and raise before any real network I/O. If the pin failed (or a
# rebinding flip pointed at a private IP), we'd either see the private IP here
# (test fails) or the request is refused before reaching the parent.
# ---------------------------------------------------------------------------

_PUBLIC_IP = "93.184.216.34"
_PRIVATE_IP = "127.0.0.1"


def _install_connect_recorder(monkeypatch, targets: list[str]):
    """Patch the real transport so it records the post-pin connect host and
    raises before any socket I/O. Returns nothing; appends to `targets`."""

    async def _recording_parent(self, request, *a, **kw):
        targets.append(request.url.host)
        # Surface the Host header + SNI so tests can assert they're preserved.
        targets.append(("host_header", request.headers.get("host")))
        targets.append(("sni", request.extensions.get("sni_hostname")))
        raise RuntimeError("network blocked in test")

    monkeypatch.setattr(
        httpx.AsyncHTTPTransport, "handle_async_request", _recording_parent
    )


def _flipping_getaddrinfo(first_ip: str, then_ip: str):
    """getaddrinfo that returns `first_ip` on call #1 and `then_ip` after — a
    low-TTL DNS-rebinding flip between the pre-flight check and the connect."""
    state = {"n": 0}

    def _fake(host, port, *a, **kw):
        state["n"] += 1
        ip = first_ip if state["n"] == 1 else then_ip
        fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
        sockaddr = (ip, port or 443, 0, 0) if fam == socket.AF_INET6 else (ip, port or 443)
        return [(fam, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]

    return _fake


@pytest.mark.asyncio
async def test_pin_connects_to_validated_public_ip(monkeypatch):
    """Stable public DNS: the connection is pinned to the validated public IP,
    while the Host header and TLS SNI keep the original hostname."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo_returning(_PUBLIC_IP))
    recorded: list = []
    _install_connect_recorder(monkeypatch, recorded)

    with pytest.raises(RuntimeError):  # our recorder raises before real I/O
        await safe_http.safe_get("https://example.com/p")

    # First recorded item is the dialed host: the validated public IP.
    assert recorded[0] == _PUBLIC_IP
    assert ("host_header", "example.com") in recorded
    assert ("sni", "example.com") in recorded
    assert _PRIVATE_IP not in recorded


@pytest.mark.asyncio
async def test_rebinding_flip_to_private_is_refused_never_connected(monkeypatch):
    """DNS-rebinding: getaddrinfo returns PUBLIC on the pre-flight check and
    PRIVATE on the connect-time lookup inside the pinning transport. The
    request must be REFUSED and the private IP must NEVER be connected to."""
    monkeypatch.setattr(
        socket, "getaddrinfo", _flipping_getaddrinfo(_PUBLIC_IP, _PRIVATE_IP)
    )
    recorded: list = []
    _install_connect_recorder(monkeypatch, recorded)

    with pytest.raises(InvalidInput):
        await safe_http.safe_get("https://example.com/p")

    # The transport re-validated at connect time, saw the private IP, and
    # raised before ever dialing — so the recorder captured nothing.
    assert recorded == []
    assert _PRIVATE_IP not in recorded


@pytest.mark.asyncio
async def test_rebinding_flip_to_other_public_still_pins_public(monkeypatch):
    """If DNS flips to a DIFFERENT but still-public IP, the connect-time
    re-validation accepts it and pins to that public IP — the private IP is
    never in play."""
    other_public = "8.8.8.8"  # genuinely public/routable for our guard
    monkeypatch.setattr(
        socket, "getaddrinfo", _flipping_getaddrinfo(_PUBLIC_IP, other_public)
    )
    recorded: list = []
    _install_connect_recorder(monkeypatch, recorded)

    with pytest.raises(RuntimeError):
        await safe_http.safe_get("https://example.com/p")

    # Whatever public IP it pinned, it is NOT a private/loopback address.
    dialed = recorded[0]
    assert dialed == other_public
    assert _PRIVATE_IP not in recorded


@pytest.mark.asyncio
async def test_safe_post_pins_to_validated_public_ip(monkeypatch):
    """safe_post (webhook delivery) also routes through the pinning transport."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo_returning(_PUBLIC_IP))
    recorded: list = []
    _install_connect_recorder(monkeypatch, recorded)

    with pytest.raises(RuntimeError):
        await safe_http.safe_post("https://hooks.example.com/wh", content=b"{}")

    assert recorded[0] == _PUBLIC_IP
    assert ("host_header", "hooks.example.com") in recorded
    assert ("sni", "hooks.example.com") in recorded


@pytest.mark.asyncio
async def test_pin_literal_public_ip_host(monkeypatch):
    """A literal public-IP host needs no SNI override; it dials the IP and
    keeps the IP as Host (no rewrite). It must still be reachable (not refused)."""
    # No DNS needed for a literal IP.
    def _boom(*a, **kw):
        raise AssertionError("getaddrinfo must not be called for a literal IP")

    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    recorded: list = []
    _install_connect_recorder(monkeypatch, recorded)

    with pytest.raises(RuntimeError):
        await safe_http.safe_get(f"https://{_PUBLIC_IP}/p")

    assert recorded[0] == _PUBLIC_IP


# ---------------------------------------------------------------------------
# Registrable-domain (public-suffix-aware) same-domain callback check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host,expected",
    [
        ("example.com", "example.com"),
        ("pay.example.com", "example.com"),
        ("deep.sub.example.com", "example.com"),
        ("Example.COM.", "example.com"),  # case + trailing dot normalised
        ("foo.co.uk", "foo.co.uk"),  # co.uk is a public suffix
        ("a.example.co.uk", "example.co.uk"),
        ("a.github.io", "a.github.io"),  # github.io tenants are separate parties
        ("x.s3.amazonaws.com", "x.s3.amazonaws.com"),
        ("github.io", "github.io"),  # host IS a public suffix
        ("localhost", "localhost"),
    ],
)
def test_registrable_domain(host, expected):
    assert wallet._registrable_domain(host) == expected


@pytest.mark.parametrize(
    "cb_host,addr_host,same",
    [
        ("pay.example.com", "example.com", True),  # subdomain OK
        ("example.com", "example.com", True),
        ("pay.Example.COM.", "example.com", True),  # case/dot insensitive
        ("attacker-controlled.net", "example.com", False),
        # Public-suffix evasion cases the OLD last-two-labels heuristic missed:
        ("bar.co.uk", "foo.co.uk", False),
        ("b.github.io", "a.github.io", False),
        ("evil.s3.amazonaws.com", "victim.s3.amazonaws.com", False),
        # Genuine same registrable domain under a ccTLD 2nd level still allowed:
        ("pay.example.co.uk", "shop.example.co.uk", True),
    ],
)
def test_same_callback_domain(cb_host, addr_host, same):
    assert wallet._same_callback_domain(cb_host, addr_host) is same


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "addr_host,callback",
    [
        # Same public suffix, different registrable domain -> must be rejected.
        ("foo.co.uk", "https://bar.co.uk/cb"),
        ("a.github.io", "https://b.github.io/cb"),
        ("victim.s3.amazonaws.com", "https://evil.s3.amazonaws.com/cb"),
    ],
)
async def test_lnurl_callback_shared_suffix_is_rejected(monkeypatch, addr_host, callback):
    """A malicious LNURL server on the SAME public suffix (but a different
    registrable domain) than the lightning-address host must not be able to
    aim the callback at itself. The old heuristic allowed these; the new
    public-suffix-aware check rejects them."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo_returning(_PUBLIC_IP))

    well_known = {
        "tag": "payRequest",
        "minSendable": 1000,
        "maxSendable": 1_000_000_000,
        "callback": callback,
    }

    async def _fake_safe_get(url, *, params=None, **kw):
        # Only the well-known fetch should ever happen; the callback is rejected
        # before any second fetch.
        assert url == f"https://{addr_host}/.well-known/lnurlp/alice"
        return _FakeResponse(well_known)

    monkeypatch.setattr(wallet, "safe_get", _fake_safe_get)

    with pytest.raises(InvalidInput):
        await wallet.resolve_lightning_address_to_invoice(f"alice@{addr_host}", 100, None)


@pytest.mark.asyncio
async def test_lnurl_callback_subdomain_same_registrable_is_allowed(monkeypatch):
    """A callback on a SUBDOMAIN of the same registrable domain (the common
    real-world LNURL-pay deployment) is still allowed."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo_returning(_PUBLIC_IP))

    well_known = {
        "tag": "payRequest",
        "minSendable": 1000,
        "maxSendable": 1_000_000_000,
        "callback": "https://pay.shop.example.co.uk/cb",
    }
    callback_resp = {"pr": "lnbc1u1pgoodinvoice"}

    async def _fake_safe_get(url, *, params=None, **kw):
        if url.endswith("/.well-known/lnurlp/alice"):
            return _FakeResponse(well_known)
        return _FakeResponse(callback_resp)

    monkeypatch.setattr(wallet, "safe_get", _fake_safe_get)

    invoice = await wallet.resolve_lightning_address_to_invoice(
        "alice@www.example.co.uk", 100, None
    )
    assert invoice == "lnbc1u1pgoodinvoice"
