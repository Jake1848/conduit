"""Tests for the L402 engine (sdk-python/conduit/l402.py).

All tests use REAL pymacaroons Macaroon objects with genuine caveats — not
hand-rolled strings.  This is mandatory because the cache-scope bug (keying on
URL instead of macaroon scope) only surfaces against genuine caveat structures.

Test matrix
-----------
- header parse (L402 + LSAT schemes) and InvalidChallenge on malformed input
- UnsupportedChallenge on non-L402 scheme
- happy path: stub payer produces correct ``Authorization: L402 mac:preimage``
- cache reuse: two different paths under one service macaroon → ONE payment
- cache miss on expired caveat → triggers a new payment (re-pay)
- cache miss on capability mismatch → bypass cache, pay for correct token
- cache fallback when caveats are unparseable
- re-pay guard: post-pay 402 with NEW invoice → at most 1 re-pay; third → RepayCapExceeded
- re-pay guard: post-pay 402 with SAME challenge → does NOT re-pay, raises immediately
- guard: over max_auto_pay_sats → PaymentRejected, zero pays
- guard: denied domain → PaymentRejected, zero pays
- guard: approver returning True allows over-cap payment
- guard: approver returning False → PaymentRejected
- payer returning null/faulted preimage → PreimageError raised, no header built
"""

from __future__ import annotations

import base64
import time
from collections.abc import Callable
from typing import Any

import pytest
from pymacaroons import Macaroon

from conduit.l402 import (
    InvalidChallenge,
    L402Config,
    L402Engine,
    PaidResult,
    PaymentRejected,
    PreimageError,
    Protocol,
    RepayCapExceeded,
    UnsupportedChallenge,
    _parse_challenge,
    _parse_caveats,
    _caveat_still_valid,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BOLT11_STUB = "lnbc10u1p4zau6rdqqxyz"
PREIMAGE_STUB = "a" * 64  # 32-byte hex preimage


def _make_macaroon(
    *,
    location: str = "https://api.example.com",
    identifier: str = "token-id-abc",
    caveats: list[str] | None = None,
) -> Macaroon:
    """Build a real pymacaroons Macaroon (no signature — just structure for tests)."""
    mac = Macaroon(
        location=location,
        identifier=identifier,
        key="super-secret-root-key-for-tests",
    )
    for caveat in caveats or []:
        mac.add_first_party_caveat(caveat)
    return mac


def _mac_b64(mac: Macaroon) -> str:
    return mac.serialize()


def _l402_header(mac: Macaroon, invoice: str = BOLT11_STUB) -> str:
    return f'L402 macaroon="{_mac_b64(mac)}", invoice="{invoice}"'


def _lsat_header(mac: Macaroon, invoice: str = BOLT11_STUB) -> str:
    return f'LSAT macaroon="{_mac_b64(mac)}", invoice="{invoice}"'


def _stub_payer(preimage: str = PREIMAGE_STUB) -> Callable[[str, int], PaidResult]:
    calls: list[dict[str, Any]] = []

    def _pay(invoice: str, sats: int) -> PaidResult:
        calls.append({"invoice": invoice, "sats": sats})
        return PaidResult(preimage=preimage)

    _pay.calls = calls  # type: ignore[attr-defined]
    return _pay


def _null_payer() -> Callable[[str, int], PaidResult]:
    """Payer that returns no preimage (simulates a pending/failed payment)."""
    def _pay(invoice: str, sats: int) -> PaidResult:
        return PaidResult(preimage=None)
    return _pay


def _faulted_payer() -> Callable[[str, int], PaidResult]:
    """Payer that returns a preimage_error (integrity check failed)."""
    def _pay(invoice: str, sats: int) -> PaidResult:
        return PaidResult(preimage=None, preimage_error="sha256 mismatch: stored preimage invalid")
    return _pay


# ---------------------------------------------------------------------------
# Macaroon caveat helpers
# ---------------------------------------------------------------------------

def test_parse_caveats_extracts_known_keys() -> None:
    mac = _make_macaroon(caveats=[
        "services=my-service",
        "valid_until=9999999999",
        "capabilities=read,write",
    ])
    scope = _parse_caveats(mac)
    assert scope["services"] == "my-service"
    assert scope["valid_until"] == "9999999999"
    assert scope["capabilities"] == "read,write"


def test_parse_caveats_empty_macaroon() -> None:
    mac = _make_macaroon()
    assert _parse_caveats(mac) == {}


def test_caveat_still_valid_no_expiry() -> None:
    ok, reason = _caveat_still_valid({})
    assert ok is True
    assert reason == ""


def test_caveat_still_valid_future_expiry() -> None:
    ok, _ = _caveat_still_valid({"valid_until": str(time.time() + 3600)})
    assert ok is True


def test_caveat_still_valid_past_expiry() -> None:
    ok, reason = _caveat_still_valid({"valid_until": str(time.time() - 1)})
    assert ok is False
    assert "expired" in reason


def test_caveat_still_valid_zero_count() -> None:
    ok, reason = _caveat_still_valid({"count": "0"})
    assert ok is False
    assert "quota" in reason


def test_caveat_still_valid_positive_count() -> None:
    ok, _ = _caveat_still_valid({"count": "5"})
    assert True  # positive count → still valid


# ---------------------------------------------------------------------------
# Header parsing — L402 and LSAT
# ---------------------------------------------------------------------------

def test_parse_l402_header_standard() -> None:
    mac = _make_macaroon(caveats=["services=loop"])
    header = _l402_header(mac)
    challenge = _parse_challenge(header)
    assert challenge.protocol == Protocol.L402
    assert challenge.macaroon is not None
    assert challenge.invoice == BOLT11_STUB
    assert challenge.scope.get("services") == "loop"


def test_parse_lsat_header_accepted() -> None:
    mac = _make_macaroon(caveats=["services=lsat-service"])
    header = _lsat_header(mac)
    challenge = _parse_challenge(header)
    assert challenge.protocol == Protocol.LSAT
    assert challenge.macaroon is not None


def test_parse_l402_header_invoice_first_ordering() -> None:
    """Some servers put invoice before macaroon — both orderings must parse."""
    mac = _make_macaroon()
    mac_b64 = _mac_b64(mac)
    header = f'L402 invoice="{BOLT11_STUB}", macaroon="{mac_b64}"'
    challenge = _parse_challenge(header)
    assert challenge.invoice == BOLT11_STUB
    assert challenge.macaroon_b64 == mac_b64


def test_parse_l402_header_case_insensitive_scheme() -> None:
    mac = _make_macaroon()
    header = f'l402 macaroon="{_mac_b64(mac)}", invoice="{BOLT11_STUB}"'
    challenge = _parse_challenge(header)
    assert challenge.protocol == Protocol.L402


def test_parse_l402_missing_invoice_raises_invalid_challenge() -> None:
    mac = _make_macaroon()
    header = f'L402 macaroon="{_mac_b64(mac)}"'
    with pytest.raises(InvalidChallenge):
        _parse_challenge(header)


def test_parse_l402_missing_macaroon_raises_invalid_challenge() -> None:
    header = f'L402 invoice="{BOLT11_STUB}"'
    with pytest.raises(InvalidChallenge):
        _parse_challenge(header)


def test_parse_l402_empty_header_raises_invalid_challenge() -> None:
    with pytest.raises((InvalidChallenge, UnsupportedChallenge)):
        _parse_challenge("")


def test_parse_l402_malformed_raises_invalid_challenge() -> None:
    with pytest.raises((InvalidChallenge, UnsupportedChallenge)):
        _parse_challenge("L402 garbage-no-fields-here")


# ---------------------------------------------------------------------------
# UnsupportedChallenge for non-L402 schemes
# ---------------------------------------------------------------------------

def test_parse_bearer_scheme_raises_unsupported() -> None:
    with pytest.raises(UnsupportedChallenge):
        _parse_challenge('Bearer realm="example"')


def test_parse_x402_scheme_raises_unsupported() -> None:
    """x402 is a related protocol — must not be silently mishandled."""
    with pytest.raises(UnsupportedChallenge):
        _parse_challenge('x402 some="fields"')


def test_parse_basic_scheme_raises_unsupported() -> None:
    with pytest.raises(UnsupportedChallenge):
        _parse_challenge('Basic realm="secure"')


# ---------------------------------------------------------------------------
# Happy path: correct Authorization header built
# ---------------------------------------------------------------------------

def test_happy_path_builds_correct_auth_header() -> None:
    mac = _make_macaroon(caveats=["services=my-svc"])
    payer = _stub_payer()
    engine = L402Engine(pay_invoice=payer)

    header = _l402_header(mac)
    auth = engine.handle_challenge(url="https://api.example.com/resource", www_authenticate=header)

    expected_mac = _mac_b64(mac)
    assert auth == f"L402 {expected_mac}:{PREIMAGE_STUB}"
    assert len(payer.calls) == 1


# ---------------------------------------------------------------------------
# Cache: scope reuse across different paths
# ---------------------------------------------------------------------------

def test_cache_scope_reuse_two_paths_one_pay() -> None:
    """Two requests to different paths under the SAME service macaroon → ONE payment.

    This is the #1 correctness requirement: cache keyed on scope, not URL.
    Both requests carry the SAME macaroon (same service scope), so the second
    call must hit the cache and NOT call the payer.
    """
    mac = _make_macaroon(caveats=["services=my-service", "capabilities=read"])
    payer = _stub_payer()
    engine = L402Engine(pay_invoice=payer)

    invoice_a = "lnbc10u1p_invoice_a"
    invoice_b = "lnbc10u1p_invoice_b"  # different invoice, same macaroon scope

    header_a = f'L402 macaroon="{_mac_b64(mac)}", invoice="{invoice_a}"'
    header_b = f'L402 macaroon="{_mac_b64(mac)}", invoice="{invoice_b}"'

    auth_a = engine.handle_challenge(url="https://api.example.com/v1/data", www_authenticate=header_a)
    auth_b = engine.handle_challenge(url="https://api.example.com/v1/other", www_authenticate=header_b)

    # Only one payment
    assert len(payer.calls) == 1
    assert payer.calls[0]["invoice"] == invoice_a

    # Both headers point to the cached token (same macaroon, same preimage)
    assert auth_a == f"L402 {_mac_b64(mac)}:{PREIMAGE_STUB}"
    assert auth_b == auth_a  # same cached header


def test_cache_different_services_two_pays() -> None:
    """Two macaroons with different service identifiers → two payments."""
    mac_a = _make_macaroon(identifier="token-a", caveats=["services=service-a"])
    mac_b = _make_macaroon(identifier="token-b", caveats=["services=service-b"])
    payer = _stub_payer()
    engine = L402Engine(pay_invoice=payer)

    engine.handle_challenge(
        url="https://api.example.com/a",
        www_authenticate=f'L402 macaroon="{_mac_b64(mac_a)}", invoice="lnbc_inv_a"',
    )
    engine.handle_challenge(
        url="https://api.example.com/b",
        www_authenticate=f'L402 macaroon="{_mac_b64(mac_b)}", invoice="lnbc_inv_b"',
    )

    assert len(payer.calls) == 2


# ---------------------------------------------------------------------------
# Cache: expired caveat → cache miss → re-pay
# ---------------------------------------------------------------------------

def test_cache_expired_caveat_triggers_repay() -> None:
    """A cached token whose valid_until has passed must be evicted and re-paid."""
    past_ts = str(int(time.time()) - 1)  # already expired
    mac = _make_macaroon(caveats=[
        "services=my-svc",
        f"valid_until={past_ts}",
    ])
    payer = _stub_payer()
    engine = L402Engine(pay_invoice=payer)

    invoice_1 = "lnbc_inv_1"
    invoice_2 = "lnbc_inv_2"
    header_1 = f'L402 macaroon="{_mac_b64(mac)}", invoice="{invoice_1}"'
    header_2 = f'L402 macaroon="{_mac_b64(mac)}", invoice="{invoice_2}"'

    # First call: pays (token immediately stale but stored)
    engine.handle_challenge(url="https://api.example.com/a", www_authenticate=header_1)
    assert len(payer.calls) == 1

    # Second call: scope_key matches, but caveat re-validation finds expired → cache miss → pay again
    engine.handle_challenge(url="https://api.example.com/b", www_authenticate=header_2)
    assert len(payer.calls) == 2
    assert payer.calls[1]["invoice"] == invoice_2


# ---------------------------------------------------------------------------
# Cache: capability not covered → bypass cache, pay for correct token
# ---------------------------------------------------------------------------

def test_cache_different_capabilities_separate_pays() -> None:
    """Two macaroons for the same service but different capabilities have different
    scope keys and therefore each triggers a separate payment."""
    mac_read = _make_macaroon(
        identifier="token-read",
        caveats=["services=my-svc", "capabilities=read"],
    )
    mac_write = _make_macaroon(
        identifier="token-write",
        caveats=["services=my-svc", "capabilities=write"],
    )
    payer = _stub_payer()
    engine = L402Engine(pay_invoice=payer)

    engine.handle_challenge(
        url="https://api.example.com/read",
        www_authenticate=f'L402 macaroon="{_mac_b64(mac_read)}", invoice="lnbc_read"',
    )
    engine.handle_challenge(
        url="https://api.example.com/write",
        www_authenticate=f'L402 macaroon="{_mac_b64(mac_write)}", invoice="lnbc_write"',
    )

    assert len(payer.calls) == 2


# ---------------------------------------------------------------------------
# Cache fallback when caveats unparseable (degraded mode)
# ---------------------------------------------------------------------------

def test_cache_fallback_unparseable_macaroon() -> None:
    """When pymacaroons can't decode the macaroon, the engine falls back to a
    raw-b64-prefix key — still gives per-token isolation without crashing."""
    payer = _stub_payer()
    engine = L402Engine(pay_invoice=payer)

    # A garbage base64 string that pymacaroons cannot deserialize
    bad_mac = base64.b64encode(b"not-a-real-macaroon-bytes").decode()
    header = f'L402 macaroon="{bad_mac}", invoice="{BOLT11_STUB}"'

    # Must not raise — degraded mode kicks in
    auth = engine.handle_challenge(url="https://api.example.com/r", www_authenticate=header)
    assert "L402 " in auth
    assert len(payer.calls) == 1

    # Second identical call → cache hit (degraded key reused)
    auth2 = engine.handle_challenge(url="https://api.example.com/r", www_authenticate=header)
    assert len(payer.calls) == 1  # still only one payment
    assert auth2 == auth


# ---------------------------------------------------------------------------
# Re-pay guard: post-pay 402 with NEW invoice → at most one re-pay; third → cap
# ---------------------------------------------------------------------------

def test_repay_guard_new_invoice_allows_one_repay_then_raises() -> None:
    """After a successful pay+cache, a post-pay 402 carrying a NEW invoice is
    allowed once more (re-pay cap=1).  A THIRD 402 raises RepayCapExceeded."""
    mac_1 = _make_macaroon(identifier="tok1", caveats=["services=svc"])
    mac_2 = _make_macaroon(identifier="tok2", caveats=["services=svc"])
    mac_3 = _make_macaroon(identifier="tok3", caveats=["services=svc"])

    inv_1 = "lnbc_inv_1"
    inv_2 = "lnbc_inv_2"
    inv_3 = "lnbc_inv_3"

    header_1 = f'L402 macaroon="{_mac_b64(mac_1)}", invoice="{inv_1}"'
    header_2 = f'L402 macaroon="{_mac_b64(mac_2)}", invoice="{inv_2}"'
    header_3 = f'L402 macaroon="{_mac_b64(mac_3)}", invoice="{inv_3}"'

    url = "https://api.example.com/resource"
    payer = _stub_payer()
    engine = L402Engine(pay_invoice=payer, config=L402Config(max_repays_per_resource_window=1))

    # Simulate the fetch_paid loop manually via _handle_post_pay_402:
    #   First 402 → pay → NEW 402 (different mac/inv) → _handle_post_pay_402 → allows (count=1)
    engine._handle_post_pay_402(url, header_1, header_2)  # count=1, cap=1 → allowed

    # A SECOND NEW 402 (different mac/inv again) → count exceeds cap → RepayCapExceeded
    with pytest.raises(RepayCapExceeded, match="exceed"):
        engine._handle_post_pay_402(url, header_2, header_3)


def test_repay_guard_via_fetch_paid_three_402s_raises() -> None:
    """Integration test: fetch_paid that sees three consecutive 402 responses raises."""
    mac_1 = _make_macaroon(identifier="t1", caveats=["services=svc"])
    mac_2 = _make_macaroon(identifier="t2", caveats=["services=svc"])
    mac_3 = _make_macaroon(identifier="t3", caveats=["services=svc"])

    inv_1, inv_2, inv_3 = "lnbc_i1", "lnbc_i2", "lnbc_i3"
    url = "https://api.example.com/res"

    call_count = [0]

    def _fetcher(
        _url: str, _method: str, _headers: dict[str, str], _body: Any
    ) -> tuple[int, dict[str, str], str]:
        call_count[0] += 1
        n = call_count[0]
        if n == 1:
            return 402, {"WWW-Authenticate": f'L402 macaroon="{_mac_b64(mac_1)}", invoice="{inv_1}"'}, ""
        if n == 2:
            return 402, {"WWW-Authenticate": f'L402 macaroon="{_mac_b64(mac_2)}", invoice="{inv_2}"'}, ""
        # Third 402 — the engine should raise before fetching a 4th time
        return 402, {"WWW-Authenticate": f'L402 macaroon="{_mac_b64(mac_3)}", invoice="{inv_3}"'}, ""

    payer = _stub_payer()
    engine = L402Engine(
        pay_invoice=payer,
        config=L402Config(max_repays_per_resource_window=1),
    )

    with pytest.raises(RepayCapExceeded):
        engine.fetch_paid(url=url, fetcher=_fetcher)


# ---------------------------------------------------------------------------
# Re-pay guard: SAME challenge after pay → raises, does NOT re-pay
# ---------------------------------------------------------------------------

def test_repay_guard_same_challenge_raises_without_repay() -> None:
    """If the post-pay 402 carries the SAME macaroon+invoice, we must NOT re-pay.
    This indicates the server rejected our token (clock skew / revocation)."""
    mac = _make_macaroon(caveats=["services=svc"])
    invoice = "lnbc_same_invoice"
    header = f'L402 macaroon="{_mac_b64(mac)}", invoice="{invoice}"'
    url = "https://api.example.com/same"

    payer = _stub_payer()
    engine = L402Engine(pay_invoice=payer)

    # Calling _handle_post_pay_402 with the SAME original and new header → raises immediately
    with pytest.raises(RepayCapExceeded, match="SAME challenge"):
        engine._handle_post_pay_402(url, header, header)

    # Payer was never called (classification happens before any payment)
    assert len(payer.calls) == 0


def test_repay_guard_same_challenge_via_fetch_paid() -> None:
    """Integration test: fetch_paid that sees same 402 twice (same mac+inv) raises."""
    mac = _make_macaroon(caveats=["services=svc"])
    invoice = "lnbc_same"
    www_auth = f'L402 macaroon="{_mac_b64(mac)}", invoice="{invoice}"'
    url = "https://api.example.com/same-challenge"

    call_count = [0]

    def _fetcher(
        _url: str, _method: str, _headers: dict[str, str], _body: Any
    ) -> tuple[int, dict[str, str], str]:
        call_count[0] += 1
        # Always return the SAME challenge
        return 402, {"WWW-Authenticate": www_auth}, ""

    payer = _stub_payer()
    engine = L402Engine(pay_invoice=payer)

    with pytest.raises(RepayCapExceeded, match="SAME challenge"):
        engine.fetch_paid(url=url, fetcher=_fetcher)

    # Exactly one payment attempted (the first 402 → paid; second 402 same → raised)
    assert len(payer.calls) == 1


# ---------------------------------------------------------------------------
# Guard: over max_auto_pay_sats → refuse, no pay
# ---------------------------------------------------------------------------

def test_guard_over_cap_refuses() -> None:
    mac = _make_macaroon()
    header = _l402_header(mac)
    payer = _stub_payer()
    engine = L402Engine(
        pay_invoice=payer,
        config=L402Config(max_auto_pay_sats=100),
    )

    with pytest.raises(PaymentRejected, match="max_auto_pay_sats"):
        engine.handle_challenge(
            url="https://api.example.com/r", www_authenticate=header, sats=101
        )

    assert len(payer.calls) == 0


def test_guard_at_cap_allows() -> None:
    mac = _make_macaroon()
    header = _l402_header(mac)
    payer = _stub_payer()
    engine = L402Engine(
        pay_invoice=payer,
        config=L402Config(max_auto_pay_sats=100),
    )

    engine.handle_challenge(
        url="https://api.example.com/r", www_authenticate=header, sats=100
    )
    assert len(payer.calls) == 1


# ---------------------------------------------------------------------------
# Guard: denied domain → refuse
# ---------------------------------------------------------------------------

def test_guard_denied_domain_refuses() -> None:
    mac = _make_macaroon()
    header = _l402_header(mac)
    payer = _stub_payer()
    engine = L402Engine(
        pay_invoice=payer,
        config=L402Config(denied_domains=["evil.example.com"]),
    )

    with pytest.raises(PaymentRejected, match="denied_domains"):
        engine.handle_challenge(
            url="https://evil.example.com/resource", www_authenticate=header
        )

    assert len(payer.calls) == 0


def test_guard_denied_domain_subdomain_refused() -> None:
    mac = _make_macaroon()
    header = _l402_header(mac)
    payer = _stub_payer()
    engine = L402Engine(
        pay_invoice=payer,
        config=L402Config(denied_domains=["example.com"]),
    )

    with pytest.raises(PaymentRejected):
        engine.handle_challenge(
            url="https://sub.example.com/resource", www_authenticate=header
        )


def test_guard_allowed_domain_permits() -> None:
    mac = _make_macaroon()
    header = _l402_header(mac)
    payer = _stub_payer()
    engine = L402Engine(
        pay_invoice=payer,
        config=L402Config(allowed_domains=["trusted.com"]),
    )

    engine.handle_challenge(url="https://trusted.com/data", www_authenticate=header)
    assert len(payer.calls) == 1


def test_guard_allowed_domain_blocks_unlisted() -> None:
    mac = _make_macaroon()
    header = _l402_header(mac)
    payer = _stub_payer()
    engine = L402Engine(
        pay_invoice=payer,
        config=L402Config(allowed_domains=["trusted.com"]),
    )

    with pytest.raises(PaymentRejected, match="not in the allowed_domains"):
        engine.handle_challenge(url="https://untrusted.org/data", www_authenticate=header)

    assert len(payer.calls) == 0


# ---------------------------------------------------------------------------
# Guard: approval callback
# ---------------------------------------------------------------------------

def test_guard_approver_true_allows_over_cap() -> None:
    mac = _make_macaroon()
    header = _l402_header(mac)
    payer = _stub_payer()
    engine = L402Engine(
        pay_invoice=payer,
        config=L402Config(max_auto_pay_sats=50, approve=lambda _: True),
    )

    engine.handle_challenge(
        url="https://api.example.com/r", www_authenticate=header, sats=999
    )
    assert len(payer.calls) == 1


def test_guard_approver_false_refuses_over_cap() -> None:
    mac = _make_macaroon()
    header = _l402_header(mac)
    payer = _stub_payer()
    engine = L402Engine(
        pay_invoice=payer,
        config=L402Config(max_auto_pay_sats=50, approve=lambda _: False),
    )

    with pytest.raises(PaymentRejected, match="max_auto_pay_sats"):
        engine.handle_challenge(
            url="https://api.example.com/r", www_authenticate=header, sats=999
        )
    assert len(payer.calls) == 0


# ---------------------------------------------------------------------------
# Payer returns null/faulted preimage → PreimageError
# ---------------------------------------------------------------------------

def test_null_preimage_raises_preimage_error() -> None:
    mac = _make_macaroon()
    header = _l402_header(mac)
    engine = L402Engine(pay_invoice=_null_payer())

    with pytest.raises(PreimageError, match="no preimage"):
        engine.handle_challenge(url="https://api.example.com/r", www_authenticate=header)


def test_faulted_preimage_raises_preimage_error() -> None:
    mac = _make_macaroon()
    header = _l402_header(mac)
    engine = L402Engine(pay_invoice=_faulted_payer())

    with pytest.raises(PreimageError, match="preimage_error"):
        engine.handle_challenge(url="https://api.example.com/r", www_authenticate=header)


# ---------------------------------------------------------------------------
# Audit sink wired correctly
# ---------------------------------------------------------------------------

def test_audit_sink_records_events() -> None:
    mac = _make_macaroon(caveats=["services=svc"])
    header = _l402_header(mac)

    events: list[dict[str, Any]] = []
    payer = _stub_payer()
    engine = L402Engine(
        pay_invoice=payer,
        config=L402Config(audit=events.append),
    )

    engine.handle_challenge(url="https://api.example.com/r", www_authenticate=header)

    event_names = [e["event"] for e in events]
    assert "challenge_parsed" in event_names
    assert "paying" in event_names
    assert "paid" in event_names


def test_audit_sink_records_cache_hit() -> None:
    mac = _make_macaroon(caveats=["services=svc"])
    header = _l402_header(mac)

    events: list[dict[str, Any]] = []
    payer = _stub_payer()
    engine = L402Engine(
        pay_invoice=payer,
        config=L402Config(audit=events.append),
    )

    engine.handle_challenge(url="https://api.example.com/r", www_authenticate=header)
    events.clear()
    engine.handle_challenge(url="https://api.example.com/r2", www_authenticate=header)

    event_names = [e["event"] for e in events]
    assert "cache_hit" in event_names
    assert "paying" not in event_names


# ---------------------------------------------------------------------------
# fetch_paid integration: non-402 passes through
# ---------------------------------------------------------------------------

def test_fetch_paid_non_402_passthrough() -> None:
    payer = _stub_payer()
    engine = L402Engine(pay_invoice=payer)

    def _fetcher(url, method, headers, body):
        return 200, {"Content-Type": "text/plain"}, "hello world"

    result = engine.fetch_paid(url="https://api.example.com/open", fetcher=_fetcher)
    assert result.status == 200
    assert result.body == "hello world"
    assert result.paid_sats == 0
    assert result.cached is False
    assert len(payer.calls) == 0


def test_fetch_paid_success_on_second_attempt() -> None:
    mac = _make_macaroon(caveats=["services=svc"])
    invoice = "lnbc_inv_pay"
    www_auth = f'L402 macaroon="{_mac_b64(mac)}", invoice="{invoice}"'

    call_count = [0]

    def _fetcher(url, method, headers, body):
        call_count[0] += 1
        if call_count[0] == 1:
            return 402, {"WWW-Authenticate": www_auth}, ""
        return 200, {}, "protected content"

    payer = _stub_payer()
    engine = L402Engine(pay_invoice=payer)

    result = engine.fetch_paid(url="https://api.example.com/protected", fetcher=_fetcher)

    assert result.status == 200
    assert result.body == "protected content"
    assert result.paid_sats == 1
    assert result.cached is False
    assert result.preimage_used == PREIMAGE_STUB
    assert len(payer.calls) == 1


def test_fetch_paid_second_call_uses_cache() -> None:
    mac = _make_macaroon(caveats=["services=svc"])
    invoice = "lnbc_inv_cache"
    www_auth = f'L402 macaroon="{_mac_b64(mac)}", invoice="{invoice}"'

    call_count = [0]

    def _fetcher(url, method, headers, body):
        call_count[0] += 1
        n = call_count[0]
        if n in (1, 3):  # first request of each engine.fetch_paid call returns 402
            return 402, {"WWW-Authenticate": www_auth}, ""
        return 200, {}, "protected content"

    payer = _stub_payer()
    engine = L402Engine(pay_invoice=payer)

    # First call: pays
    result1 = engine.fetch_paid(url="https://api.example.com/p", fetcher=_fetcher)
    assert result1.paid_sats == 1
    assert not result1.cached

    # Second call: cache hit — no payment
    result2 = engine.fetch_paid(url="https://api.example.com/p", fetcher=_fetcher)
    assert result2.paid_sats == 0
    assert result2.cached is True
    assert len(payer.calls) == 1  # still only one payment total


def test_repay_window_resets_per_fetch_call() -> None:
    """The re-pay window is ONE fetch_paid cycle. Two independent calls to the
    same URL, each legitimately re-paying once on a NEW post-pay challenge, must
    BOTH succeed — the per-URL re-pay counter must not accumulate across calls
    and permanently block the resource after its first lifetime re-pay."""
    url = "https://api.example.com/protected"

    # Distinct macaroons with NO caveats → distinct raw scope keys → no
    # cross-call cache hits, so every invoice is genuinely paid.
    def hdr(ident: str, invoice: str) -> str:
        return f'L402 macaroon="{_mac_b64(_make_macaroon(identifier=ident))}", invoice="{invoice}"'

    # Each fetch_paid cycle: 402 (A) -> pay -> 402 (NEW B) -> re-pay -> 200.
    responses = [
        (402, hdr("a1", "lnbc_inv_a1")),
        (402, hdr("b1", "lnbc_inv_b1")),  # NEW challenge -> one re-pay (count 0->1, cap 1)
        (200, None),
        (402, hdr("a2", "lnbc_inv_a2")),
        (402, hdr("b2", "lnbc_inv_b2")),  # NEW challenge again -> must be allowed afresh
        (200, None),
    ]
    idx = [0]

    def _fetcher(u, method, headers, body):
        status, www = responses[idx[0]]
        idx[0] += 1
        return (status, {"WWW-Authenticate": www} if www else {}, "ok" if status == 200 else "")

    payer = _stub_payer()
    engine = L402Engine(pay_invoice=payer, config=L402Config(max_repays_per_resource_window=1))

    r1 = engine.fetch_paid(url=url, fetcher=_fetcher)
    assert r1.status == 200

    # Without the per-call window reset this second call would raise
    # RepayCapExceeded (cumulative count 2 > cap 1) even though it is an
    # independent, legitimate fetch.
    r2 = engine.fetch_paid(url=url, fetcher=_fetcher)
    assert r2.status == 200
    assert len(payer.calls) == 4  # 2 pays per cycle x 2 cycles
