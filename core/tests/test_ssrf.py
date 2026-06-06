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
