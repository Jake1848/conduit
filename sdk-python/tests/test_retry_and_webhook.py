"""Tests for SDK retry/backoff, idempotency-key handling, and webhook verify."""

import hashlib
import hmac

import httpx
import pytest

import conduit
from conduit.client import Conduit
from conduit.errors import ConduitError, RateLimited, WebhookVerificationError
from conduit.webhook import parse_webhook, verify_webhook


# ---------- helpers ----------

class Recorder(httpx.MockTransport):
    """A MockTransport that records every request and dispatches to a
    responder(request, attempt_number) callable."""

    def __init__(self, responder):
        self.requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return responder(request, len(self.requests))

        super().__init__(handler)


def _receipt_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        201,
        json={
            "id": "tx_1",
            "agent_id": "agt_1",
            "status": "settled",
            "hash": "ab" * 32,
            "amount_sats": 100,
            "fee_sats": 1,
            "settled_in_ms": 5,
            "destination": "02" + "aa" * 32,
            "memo": None,
            "created_at": "2026-05-27T00:00:00+00:00",
        },
    )


def _make_client(transport: httpx.MockTransport, **kw) -> Conduit:
    c = Conduit(api_key="ck_test_x", base_url="http://mock", **kw)
    # Swap in the recording transport.
    c._client = httpx.Client(
        base_url="http://mock",
        transport=transport,
        headers={
            "Authorization": "Bearer ck_test_x",
            "Content-Type": "application/json",
        },
    )
    return c


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Record sleeps instead of actually sleeping."""
    slept: list[float] = []
    monkeypatch.setattr("conduit.client.time.sleep", lambda d: slept.append(d))
    return slept


# ---------- retry behavior ----------

def test_retries_on_429_then_succeeds(_no_sleep):
    def responder(request, n):
        if n == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "0"},
                json={"detail": {"code": "RATE_LIMITED", "detail": "slow down"}},
            )
        return _receipt_response(request)

    t = Recorder(responder)
    c = _make_client(t, retry_backoff_base=0.0)
    data = c.post("/v1/payments/send", json={"sats": 100}, idempotency_key="key-abc")
    assert data["status"] == "settled"
    assert len(t.requests) == 2  # one retry
    # Same idempotency key on both attempts — the whole point.
    keys = {r.headers.get("Idempotency-Key") for r in t.requests}
    assert keys == {"key-abc"}


def test_retries_on_503_then_succeeds(_no_sleep):
    def responder(request, n):
        if n <= 2:
            return httpx.Response(503, json={"detail": {"detail": "unavailable"}})
        return _receipt_response(request)

    t = Recorder(responder)
    c = _make_client(t, retry_backoff_base=0.0)
    data = c.post("/v1/payments/send", json={"sats": 100}, idempotency_key="k")
    assert data["status"] == "settled"
    assert len(t.requests) == 3  # two retries


def test_does_not_retry_on_4xx(_no_sleep):
    def responder(request, n):
        return httpx.Response(
            400, json={"detail": {"code": "INVALID_INPUT", "detail": "bad"}}
        )

    t = Recorder(responder)
    c = _make_client(t)
    with pytest.raises(ConduitError):
        c.post("/v1/payments/send", json={"sats": 0})
    assert len(t.requests) == 1  # no retries on a 4xx


def test_exhausts_retries_then_raises(_no_sleep):
    def responder(request, n):
        return httpx.Response(429, json={"detail": {"code": "RATE_LIMITED", "detail": "no"}})

    t = Recorder(responder)
    c = _make_client(t, max_retries=3, retry_backoff_base=0.0)
    with pytest.raises(RateLimited):
        c.post("/v1/payments/send", json={"sats": 100}, idempotency_key="k")
    # 1 initial + 3 retries = 4 attempts.
    assert len(t.requests) == 4


def test_honors_retry_after_header(_no_sleep):
    def responder(request, n):
        if n == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "2"},
                json={"detail": {"code": "RATE_LIMITED", "detail": "wait"}},
            )
        return _receipt_response(request)

    t = Recorder(responder)
    # Large backoff base so we can tell Retry-After (2s) overrode it.
    c = _make_client(t, retry_backoff_base=30.0)
    c.post("/v1/payments/send", json={"sats": 100}, idempotency_key="k")
    assert _no_sleep == [2.0]  # honored the header, not 30s backoff


def test_retries_on_network_error(_no_sleep):
    def responder(request, n):
        if n == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return _receipt_response(request)

    t = Recorder(responder)
    c = _make_client(t, retry_backoff_base=0.0)
    data = c.post("/v1/payments/send", json={"sats": 100}, idempotency_key="k")
    assert data["status"] == "settled"
    assert len(t.requests) == 2


def test_exponential_backoff_sequence(_no_sleep):
    def responder(request, n):
        if n <= 3:
            return httpx.Response(500, json={"detail": {"detail": "boom"}})
        return _receipt_response(request)

    t = Recorder(responder)
    c = _make_client(t, max_retries=3, retry_backoff_base=1.0)
    c.post("/v1/payments/send", json={"sats": 100}, idempotency_key="k")
    assert _no_sleep == [1.0, 2.0, 4.0]


def test_parse_retry_after():
    from conduit.client import _parse_retry_after

    assert _parse_retry_after("3") == 3.0
    assert _parse_retry_after("0") == 0.0
    assert _parse_retry_after("") is None         # empty → exponential fallback
    assert _parse_retry_after("   ") is None       # whitespace → fallback
    assert _parse_retry_after("-5") is None        # negative → fallback
    assert _parse_retry_after("abc") is None       # non-numeric → fallback


def test_empty_retry_after_falls_back_to_exponential(_no_sleep):
    """An empty Retry-After header must not collapse the backoff to 0; it
    should fall back to exponential (parity with the JS SDK)."""
    def responder(request, n):
        if n == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": ""},
                json={"detail": {"code": "RATE_LIMITED", "detail": "x"}},
            )
        return _receipt_response(request)

    t = Recorder(responder)
    c = _make_client(t, retry_backoff_base=1.0)
    c.post("/v1/payments/send", json={"sats": 100}, idempotency_key="k")
    assert _no_sleep == [1.0]  # exponential, not an instant 0-delay retry


# ---------- idempotency key auto-generation via Agent ----------

@pytest.fixture
def agent_env(monkeypatch):
    monkeypatch.setenv("CONDUIT_API_KEY", "ck_test_x")
    conduit.api_key = "ck_test_x"
    conduit.base_url = "http://mock"
    import conduit.client as cc
    cc._default = None
    yield
    cc._default = None


def test_agent_keysend_autogenerates_idempotency_key(agent_env, monkeypatch, _no_sleep):
    captured: list[httpx.Request] = []

    def responder(request, n):
        captured.append(request)
        return _receipt_response(request)

    t = Recorder(responder)
    orig = Conduit.__init__

    def patched(self, *a, **kw):
        orig(self, *a, **kw)
        self._client = httpx.Client(
            base_url="http://mock", transport=t,
            headers={"Authorization": "Bearer ck_test_x"},
        )

    monkeypatch.setattr(Conduit, "__init__", patched)

    # Build agent directly (skip the create round-trip).
    from datetime import UTC, datetime

    from conduit.agent import Agent

    agent = Agent(
        id="agt_1", name="a", pubkey=None, active=True,
        created_at=datetime.now(UTC),
    )
    agent.keysend("02" + "aa" * 32, 100)
    agent.keysend("02" + "bb" * 32, 100)

    keys = [r.headers.get("Idempotency-Key") for r in captured]
    assert all(k for k in keys), "every payment must carry an Idempotency-Key"
    assert keys[0] != keys[1], "each call generates a fresh key"
    # Look like UUID4s.
    import uuid
    for k in keys:
        uuid.UUID(k)  # raises if not a valid UUID


def test_agent_keysend_respects_explicit_key(agent_env, monkeypatch, _no_sleep):
    captured: list[httpx.Request] = []

    def responder(request, n):
        captured.append(request)
        return _receipt_response(request)

    t = Recorder(responder)
    orig = Conduit.__init__

    def patched(self, *a, **kw):
        orig(self, *a, **kw)
        self._client = httpx.Client(
            base_url="http://mock", transport=t,
            headers={"Authorization": "Bearer ck_test_x"},
        )

    monkeypatch.setattr(Conduit, "__init__", patched)
    from datetime import UTC, datetime

    from conduit.agent import Agent

    agent = Agent(
        id="agt_1", name="a", pubkey=None, active=True, created_at=datetime.now(UTC)
    )
    agent.keysend("02" + "aa" * 32, 100, idempotency_key="my-fixed-key")
    assert captured[0].headers.get("Idempotency-Key") == "my-fixed-key"


# ---------- webhook verification ----------

SECRET = "whsec_test_secret"
PAYLOAD = b'{"data":{"transaction_id":"tx_1"},"event":"payment.settled","ts":1748140800}'


def _good_sig(payload: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


def test_verify_webhook_accepts_valid_signature():
    sig = _good_sig(PAYLOAD, SECRET)
    assert verify_webhook(PAYLOAD, sig, SECRET) is True


def test_verify_webhook_rejects_tampered_payload():
    sig = _good_sig(PAYLOAD, SECRET)
    assert verify_webhook(PAYLOAD + b" ", sig, SECRET) is False


def test_verify_webhook_rejects_wrong_secret():
    sig = _good_sig(PAYLOAD, SECRET)
    assert verify_webhook(PAYLOAD, sig, "wrong-secret") is False


def test_verify_webhook_rejects_empty_signature():
    assert verify_webhook(PAYLOAD, "", SECRET) is False


def test_verify_webhook_accepts_str_payload():
    sig = _good_sig(PAYLOAD, SECRET)
    assert verify_webhook(PAYLOAD.decode(), sig, SECRET) is True


def test_parse_webhook_returns_dict():
    sig = _good_sig(PAYLOAD, SECRET)
    event = parse_webhook(PAYLOAD, sig, SECRET)
    assert event["event"] == "payment.settled"
    assert event["data"]["transaction_id"] == "tx_1"


def test_parse_webhook_raises_on_bad_signature():
    with pytest.raises(WebhookVerificationError):
        parse_webhook(PAYLOAD, "sha256=deadbeef", SECRET)
