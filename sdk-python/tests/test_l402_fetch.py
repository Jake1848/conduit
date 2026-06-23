"""U3 — fetch_with_l402 / L402Client httpx middleware.

Drives the real engine through an httpx MockTransport: a no-auth request gets a
402 + L402 challenge; once an `Authorization` header is present the server
returns 200. Verifies transparent pay+retry, non-402 passthrough, and that a
reused client's token cache prevents a second payment.
"""

from types import SimpleNamespace

import httpx
import pytest
from pymacaroons import Macaroon

from conduit.l402_fetch import L402Client, fetch_with_l402

PREIMAGE = "ab" * 32
INVOICE = "lnbc_inv_demo"


def _www_auth() -> str:
    mac = Macaroon(location="https://api.example.com", identifier="id", key="k")
    mac.add_first_party_caveat("services=demo")
    return f'L402 macaroon="{mac.serialize()}", invoice="{INVOICE}"'


class _FakeAgent:
    """Minimal stand-in: agent_payer only reads receipt.preimage/preimage_error."""

    def __init__(self) -> None:
        self.pays: list[tuple[str, int]] = []

    def pay(self, *, to: str, sats: int):
        self.pays.append((to, sats))
        return SimpleNamespace(preimage=PREIMAGE, preimage_error=None)


def _paywalled_handler(www_auth: str):
    """402 until an Authorization header is presented, then 200."""

    def handler(request: httpx.Request) -> httpx.Response:
        has_auth = any(k.lower() == "authorization" for k in request.headers)
        if has_auth:
            return httpx.Response(200, text="paid content")
        return httpx.Response(402, headers={"WWW-Authenticate": www_auth})

    return handler


def test_fetch_with_l402_pays_and_returns_body():
    agent = _FakeAgent()
    client = httpx.Client(transport=httpx.MockTransport(_paywalled_handler(_www_auth())))
    result = fetch_with_l402(
        "https://api.example.com/paid", agent=agent, sats=210, client=client
    )
    assert result.status == 200
    assert result.body == "paid content"
    assert result.paid_sats == 210
    assert agent.pays == [(INVOICE, 210)]


def test_non_402_passes_through_without_paying():
    agent = _FakeAgent()
    client = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, text="open"))
    )
    result = fetch_with_l402("https://api.example.com/open", agent=agent, client=client)
    assert result.status == 200
    assert result.body == "open"
    assert result.paid_sats == 0
    assert agent.pays == []


def test_l402client_reuses_token_across_calls():
    agent = _FakeAgent()
    client = httpx.Client(transport=httpx.MockTransport(_paywalled_handler(_www_auth())))
    with L402Client(agent, client=client) as http:
        r1 = http.fetch("https://api.example.com/a", sats=210)
        r2 = http.fetch("https://api.example.com/b", sats=210)

    assert r1.status == 200 and r2.status == 200
    assert r1.paid_sats == 210
    assert r2.paid_sats == 0 and r2.cached is True  # same-service token reused
    assert len(agent.pays) == 1  # paid once, reused for the second path


def test_over_cap_refuses_before_paying():
    from conduit.l402 import L402Config, PaymentRejected

    agent = _FakeAgent()
    client = httpx.Client(transport=httpx.MockTransport(_paywalled_handler(_www_auth())))
    with pytest.raises(PaymentRejected):
        fetch_with_l402(
            "https://api.example.com/paid",
            agent=agent,
            sats=5000,
            config=L402Config(max_auto_pay_sats=1000),
            client=client,
        )
    assert agent.pays == []  # guard fired before any payment
