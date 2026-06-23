"""L402 payment-channel engine for the Conduit SDK.

Public API
----------
Typical usage:

    from conduit.l402 import L402Engine, L402Config

    def my_payer(invoice: str, sats: int) -> PaidResult:
        receipt = agent.pay(to=invoice, sats=sats)
        return PaidResult(preimage=receipt.preimage, preimage_error=receipt.preimage_error)

    engine = L402Engine(pay_invoice=my_payer, config=L402Config(max_auto_pay_sats=5000))

    # On a 402 response:
    auth_header = engine.handle_challenge(
        url="https://api.example.com/resource",
        www_authenticate=response.headers["WWW-Authenticate"],
    )
    # Then replay the request with Authorization: <auth_header>

    # Or use the full interceptor pattern that handles the retry loop:
    body = engine.fetch_paid(
        url="https://api.example.com/resource",
        fetcher=my_httpx_get,   # callable(url, headers) -> (status, headers, body)
    )

Design notes
------------
- The engine is HTTP-client-agnostic: it does NOT do HTTP itself.  Callers supply
  a ``fetcher`` callable (or handle the replay loop themselves).
- The token cache is keyed on MACAROON SCOPE (service identifier + capability
  caveats), NOT origin+URL.  One macaroon that authorises a whole service is
  reused across all paths under that service without re-paying.
- Caveats are re-validated before every reuse: expiry, capability, quota.
- Post-pay 402 guard: if a retried fetch still returns 402 the engine classifies
  SAME vs NEW challenge and enforces a per-resource-per-window re-pay cap (default 1).
- Guards run in order BEFORE paying: domain → sats-cap → approval-callback.
- Typed errors: InvalidChallenge, UnsupportedChallenge, PaymentRejected,
  RepayCapExceeded, PreimageError.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from urllib.parse import urlparse

from pymacaroons import Macaroon


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------


class L402Error(Exception):
    """Base for all L402 engine errors."""


class InvalidChallenge(L402Error):
    """The WWW-Authenticate header could not be parsed as a valid L402 challenge."""


class UnsupportedChallenge(L402Error):
    """The WWW-Authenticate header carries a recognised but unimplemented scheme."""


class PaymentRejected(L402Error):
    """The engine refused to pay — domain blocked, sats cap exceeded, or approval denied."""


class RepayCapExceeded(L402Error):
    """A post-pay 402 on the same resource has exceeded the per-window re-pay cap."""


class PreimageError(L402Error):
    """Payment settled but the payer returned no preimage (or a faulted one).
    Building an Authorization header from a missing/faulted preimage is forbidden."""


# ---------------------------------------------------------------------------
# Protocol detection
# ---------------------------------------------------------------------------


class Protocol(Enum):
    L402 = "L402"
    # LSAT is the legacy name for L402 — treated identically.
    LSAT = "LSAT"


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class PaidResult:
    """What the caller's payer callable must return."""

    preimage: str | None
    preimage_error: str | None = None


@dataclass
class ParsedChallenge:
    """Parsed result of a WWW-Authenticate: L402/LSAT header."""

    protocol: Protocol
    macaroon_b64: str   # raw base64 string from the header
    invoice: str        # BOLT11 invoice string
    # Decoded macaroon (may be None if pymacaroons cannot decode it)
    macaroon: Macaroon | None = None
    # Parsed scope fields extracted from caveats (may be empty dict)
    scope: dict[str, str] = field(default_factory=dict)
    # The canonical scope key used for cache lookups
    scope_key: str = ""


@dataclass
class CachedToken:
    """A cached L402 credential, ready to replay as an Authorization header."""

    auth_header: str       # "L402 <macaroon>:<preimage>"
    macaroon_b64: str
    preimage: str
    scope_key: str
    scope: dict[str, str]
    paid_sats: int
    acquired_at: float = field(default_factory=time.time)


@dataclass
class FetchResult:
    """Return value from ``engine.fetch_paid``."""

    status: int
    body: str | bytes
    headers: dict[str, str]
    paid_sats: int
    cached: bool
    preimage_used: str | None


# ---------------------------------------------------------------------------
# Config / guards
# ---------------------------------------------------------------------------


@dataclass
class L402Config:
    """Configuration for client-side L402 guards (R7).

    Guards run in order BEFORE paying:
      1. domain check (denied_domains, allowed_domains)
      2. sats cap (max_auto_pay_sats)
      3. approval callback

    ``max_repays_per_resource_window`` enforces the R10 re-pay cap; default 1
    means: after one successful pay+cache, a post-pay 402 on a NEW challenge is
    allowed once more; a third 402 raises RepayCapExceeded.

    ``audit`` receives a dict for every engine decision (paid, cached, refused,
    approved, etc.).  Defaults to no-op.
    """

    max_auto_pay_sats: int | None = None
    allowed_domains: list[str] | None = None
    denied_domains: list[str] | None = None
    approve: Callable[[ParsedChallenge], bool] | None = None
    max_repays_per_resource_window: int = 1
    audit: Callable[[dict[str, Any]], None] | None = None


# ---------------------------------------------------------------------------
# Caveat parsing helpers
# ---------------------------------------------------------------------------

# Aperture/L402 servers (the reference implementation) emit caveats in the form
#   "key=value"
# Common known keys (case-insensitive for resilience):
#   services           e.g. "loop, lnd"  (service names this macaroon authorises)
#   valid_until        RFC-3339 / unix-epoch expiry
#   capabilities       comma-separated list of permitted capabilities per service
#   max_payment_amount max sats this macaroon will unlock
#   count              quota remaining (decrement model)
#   service_tier       e.g. "premium"
#
# We store them all in a flat dict with lowercased keys.

_CAVEAT_RE = re.compile(r"^([^=]+)=(.*)$")


def _parse_caveats(mac: Macaroon) -> dict[str, str]:
    """Extract all first-party caveats from a macaroon into a flat dict.

    Caveats with duplicate keys keep the LAST value (mirrors Aperture's own
    accumulation order).  Third-party caveats (encrypted) are ignored — they
    carry no plaintext we can inspect client-side.
    """
    result: dict[str, str] = {}
    for caveat in mac.caveats:
        identifier = caveat.caveat_id
        if isinstance(identifier, bytes):
            try:
                identifier = identifier.decode("utf-8")
            except UnicodeDecodeError:
                continue  # skip unreadable third-party caveats
        m = _CAVEAT_RE.match(identifier.strip())
        if m:
            key = m.group(1).strip().lower()
            val = m.group(2).strip()
            result[key] = val
    return result


def _scope_key_from_caveats(mac: Macaroon, caveats: dict[str, str]) -> str:
    """Compute a stable cache key from the macaroon's declared scope.

    Preferred key = service identifier(s) from the ``services`` caveat, as used
    by Aperture.  Falls back to the macaroon's own identifier (always present —
    it encodes the payment-hash binding and is unique per token).

    A token with NO parseable caveats falls through to the macaroon identifier,
    which gives per-token caching (safe but not scope-sharing).  This degraded
    mode is documented on ``ParsedChallenge.scope_key``.
    """
    if "services" in caveats:
        # Normalise: strip whitespace, lowercase, sort for determinism
        services = ",".join(sorted(s.strip().lower() for s in caveats["services"].split(",")))
        caps = caveats.get("capabilities", "")
        if caps:
            caps_norm = ",".join(sorted(c.strip().lower() for c in caps.split(",")))
            return f"svc:{services}|caps:{caps_norm}"
        return f"svc:{services}"
    # No service caveat — fall back to the macaroon identifier.
    identifier = mac.identifier
    if isinstance(identifier, bytes):
        try:
            identifier = identifier.decode("utf-8")
        except UnicodeDecodeError:
            identifier = identifier.hex()
    return f"mac:{identifier}"


def _caveat_still_valid(scope: dict[str, str]) -> tuple[bool, str]:
    """Re-validate the scope's time/quota caveats.

    Returns (ok, reason).  ``ok=False`` means the cached token should be
    treated as a cache MISS and a new payment must occur.
    """
    # Expiry check
    if "valid_until" in scope:
        val = scope["valid_until"].strip()
        # Try unix epoch first, then RFC-3339 / ISO-8601
        try:
            expiry = float(val)
        except ValueError:
            try:
                from datetime import datetime

                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                expiry = dt.timestamp()
            except ValueError:
                expiry = None  # unknown format — don't block reuse
        if expiry is not None and time.time() >= expiry:
            return False, "token expired (valid_until)"

    # Quota / count check — if a ``count`` caveat is present and ≤0 we treat as
    # exhausted.  Real servers decrement server-side; we can only detect "already
    # zero" from the original issuance, which is a signal that the token was
    # pre-exhausted at issue time.  In practice this guard mainly catches
    # single-use tokens issued with count=1 that were already consumed.
    if "count" in scope:
        try:
            if int(scope["count"]) <= 0:
                return False, "token quota exhausted (count≤0)"
        except ValueError:
            pass  # unparseable count — don't block

    return True, ""


# ---------------------------------------------------------------------------
# Header parsing
# ---------------------------------------------------------------------------

# Both "L402" and "LSAT" schemes use the same header format.
_HEADER_SCHEME_RE = re.compile(
    r"""^(?P<scheme>L402|LSAT)\s+
        macaroon\s*=\s*"(?P<macaroon>[^"]+)"
        .*?
        invoice\s*=\s*"(?P<invoice>[^"]+)"
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Some servers swap the order (invoice first, then macaroon).
_HEADER_SCHEME_RE_ALT = re.compile(
    r"""^(?P<scheme>L402|LSAT)\s+
        invoice\s*=\s*"(?P<invoice>[^"]+)"
        .*?
        macaroon\s*=\s*"(?P<macaroon>[^"]+)"
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _detect_protocol(www_authenticate: str) -> Protocol:
    """Return the Protocol enum for the challenge, or raise UnsupportedChallenge."""
    header = www_authenticate.strip()
    first_token = header.split()[0].upper() if header else ""
    if first_token in ("L402", "LSAT"):
        return Protocol[first_token]
    raise UnsupportedChallenge(
        f"WWW-Authenticate scheme {first_token!r} is not supported by this engine. "
        "Only L402 (and legacy LSAT) challenges are implemented."
    )


def _parse_challenge(www_authenticate: str) -> ParsedChallenge:
    """Parse a ``WWW-Authenticate: L402 macaroon="...", invoice="..."`` header.

    Accepts both field orderings and both L402 and LSAT schemes.
    Raises ``InvalidChallenge`` on any parse failure.
    Raises ``UnsupportedChallenge`` for unrecognised schemes.
    """
    protocol = _detect_protocol(www_authenticate)

    m = _HEADER_SCHEME_RE.match(www_authenticate) or _HEADER_SCHEME_RE_ALT.match(www_authenticate)
    if not m:
        raise InvalidChallenge(
            f"Could not parse {protocol.value} challenge from WWW-Authenticate header. "
            "Expected: macaroon=\"<base64>\" and invoice=\"<bolt11>\""
        )

    macaroon_b64 = m.group("macaroon").strip()
    invoice = m.group("invoice").strip()

    if not macaroon_b64:
        raise InvalidChallenge("L402 challenge contains empty macaroon field.")
    if not invoice:
        raise InvalidChallenge("L402 challenge contains empty invoice field.")
    if not (invoice.lower().startswith("ln") or ":" in invoice):
        raise InvalidChallenge(
            f"L402 challenge invoice does not look like a BOLT11 string: {invoice[:40]!r}"
        )

    # Decode the macaroon (best-effort — failures fall back to degraded mode)
    mac: Macaroon | None = None
    scope: dict[str, str] = {}
    scope_key: str = ""

    try:
        mac = Macaroon.deserialize(macaroon_b64)
        scope = _parse_caveats(mac)
        scope_key = _scope_key_from_caveats(mac, scope)
    except Exception:  # noqa: BLE001
        # pymacaroons couldn't decode it — fall back to using the raw b64 string as key.
        # This is the documented degraded mode (per the plan: "Falling back to
        # origin/url keying is allowed ONLY when caveats are absent/unparseable").
        # Using the raw macaroon bytes as key is strictly better than URL-keying:
        # it's still per-token rather than per-path.
        scope_key = f"raw:{macaroon_b64[:64]}"

    return ParsedChallenge(
        protocol=protocol,
        macaroon_b64=macaroon_b64,
        invoice=invoice,
        macaroon=mac,
        scope=scope,
        scope_key=scope_key,
    )


# ---------------------------------------------------------------------------
# Token store (pluggable)
# ---------------------------------------------------------------------------


class TokenStore:
    """In-memory token cache keyed on macaroon scope.

    Swap this out for a persistent store (e.g. Redis, SQLite) by subclassing
    and overriding get/set/delete.
    """

    def __init__(self) -> None:
        self._store: dict[str, CachedToken] = {}

    def get(self, scope_key: str) -> CachedToken | None:
        return self._store.get(scope_key)

    def set(self, token: CachedToken) -> None:
        self._store[token.scope_key] = token

    def delete(self, scope_key: str) -> None:
        self._store.pop(scope_key, None)

    def clear(self) -> None:
        self._store.clear()


# ---------------------------------------------------------------------------
# Re-pay guard state (per resource URL, per window)
# ---------------------------------------------------------------------------


@dataclass
class _RepayRecord:
    """Tracks how many times we've re-paid for a given resource in the current window."""

    count: int = 0
    last_challenge_fingerprint: str = ""


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------


class L402Engine:
    """HTTP-client-agnostic L402 payment engine.

    Parameters
    ----------
    pay_invoice:
        A callable ``(invoice: str, sats: int) -> PaidResult``.  The engine
        does NOT import or reference ``conduit.Agent`` directly — the caller
        supplies this.  This makes the engine usable from the SDK, the MCP
        server, or any other context.
    config:
        Client-side guard configuration (sats cap, domain filter, approval
        callback, re-pay cap, audit sink).
    store:
        Pluggable token store.  Defaults to an in-memory dict.
    """

    def __init__(
        self,
        pay_invoice: Callable[[str, int], PaidResult],
        config: L402Config | None = None,
        store: TokenStore | None = None,
    ) -> None:
        self._pay_invoice = pay_invoice
        self._config = config or L402Config()
        self._store = store or TokenStore()
        # Re-pay tracking: resource_url → _RepayRecord
        self._repay: dict[str, _RepayRecord] = {}

    # ------------------------------------------------------------------
    # Public: handle a 402 challenge and return an Authorization header
    # ------------------------------------------------------------------

    def handle_challenge(
        self,
        url: str,
        www_authenticate: str,
        sats: int = 1,
    ) -> str:
        """Parse the L402 challenge, check cache, pay if necessary.

        Returns an ``Authorization: L402 <macaroon>:<preimage>`` header value.

        Parameters
        ----------
        url:
            The URL that returned 402 (used for domain guard and re-pay tracking).
        www_authenticate:
            The full ``WWW-Authenticate`` header value.
        sats:
            Amount to pay.  Many L402 invoices are self-describing; pass the
            invoice amount if known, or a reasonable default.

        Raises
        ------
        InvalidChallenge, UnsupportedChallenge, PaymentRejected,
        RepayCapExceeded, PreimageError.
        """
        challenge = _parse_challenge(www_authenticate)
        self._audit("challenge_parsed", url=url, scope_key=challenge.scope_key)

        # 1. Guard: domain check
        self._guard_domain(url, challenge)

        # 2. Cache lookup
        cached = self._store.get(challenge.scope_key)
        if cached is not None:
            ok, reason = _caveat_still_valid(cached.scope)
            if ok:
                self._audit("cache_hit", url=url, scope_key=challenge.scope_key)
                return cached.auth_header
            else:
                self._audit(
                    "cache_miss_stale", url=url, scope_key=challenge.scope_key, reason=reason
                )
                self._store.delete(challenge.scope_key)

        # 3. Guard: sats cap + approval
        self._guard_cap_and_approval(url, challenge, sats)

        # 4. Pay
        self._audit("paying", url=url, scope_key=challenge.scope_key, sats=sats)
        result = self._pay_invoice(challenge.invoice, sats)
        self._check_preimage(result)

        auth_header = f"L402 {challenge.macaroon_b64}:{result.preimage}"
        token = CachedToken(
            auth_header=auth_header,
            macaroon_b64=challenge.macaroon_b64,
            preimage=result.preimage,  # type: ignore[arg-type]
            scope_key=challenge.scope_key,
            scope=challenge.scope,
            paid_sats=sats,
        )
        self._store.set(token)
        self._audit("paid", url=url, scope_key=challenge.scope_key, sats=sats)
        return auth_header

    # ------------------------------------------------------------------
    # Public: full interceptor — fetch, 402-detect, pay, replay
    # ------------------------------------------------------------------

    def fetch_paid(
        self,
        url: str,
        fetcher: Callable[..., tuple[int, dict[str, str], str | bytes]],
        sats: int = 1,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | bytes | None = None,
    ) -> FetchResult:
        """Fetch a URL, transparently paying L402 tolls if required.

        ``fetcher`` must have the signature::

            def fetcher(
                url: str,
                method: str,
                headers: dict[str, str],
                body: str | bytes | None,
            ) -> tuple[int, dict[str, str], str | bytes]:
                ...

        Returns ``FetchResult`` on success.  Raises on unrecoverable errors.
        """
        request_headers = dict(headers or {})

        # The re-pay window is a SINGLE fetch cycle: each top-level fetch_paid
        # call gets a fresh re-pay budget for this URL. Without this reset the
        # per-URL counter would accumulate across independent calls and
        # permanently refuse a resource after its first lifetime re-pay — a
        # legitimate app re-fetching the same paywalled URL would eventually be
        # blocked. Within a cycle, runaway re-paying is still bounded (at most
        # one re-pay, then the status3==402 check raises).
        self._repay.pop(url, None)

        # --- First attempt ---
        status, resp_headers, resp_body = fetcher(url, method, request_headers, body)

        if status != 402:
            return FetchResult(
                status=status,
                body=resp_body,
                headers=resp_headers,
                paid_sats=0,
                cached=False,
                preimage_used=None,
            )

        www_auth = resp_headers.get("WWW-Authenticate") or resp_headers.get("www-authenticate", "")
        if not www_auth:
            raise InvalidChallenge("Server returned 402 with no WWW-Authenticate header.")

        # Check if we have a cached token that covers this challenge's scope.
        challenge = _parse_challenge(www_auth)
        cached = self._store.get(challenge.scope_key)
        was_cached = False

        if cached is not None:
            ok, _ = _caveat_still_valid(cached.scope)
            if ok:
                was_cached = True
                auth_value = cached.auth_header
                paid_sats = 0
                preimage_used = cached.preimage
            else:
                self._store.delete(challenge.scope_key)
                cached = None

        if not was_cached:
            # Pay for the first time (guards run inside handle_challenge)
            auth_value = self.handle_challenge(url, www_auth, sats=sats)
            cached_now = self._store.get(challenge.scope_key)
            paid_sats = sats
            preimage_used = cached_now.preimage if cached_now else None

        # --- Replay with Authorization ---
        request_headers["Authorization"] = auth_value
        status2, resp_headers2, resp_body2 = fetcher(url, method, request_headers, body)

        if status2 != 402:
            return FetchResult(
                status=status2,
                body=resp_body2,
                headers=resp_headers2,
                paid_sats=paid_sats if not was_cached else 0,
                cached=was_cached,
                preimage_used=preimage_used,
            )

        # --- Post-pay 402: classify SAME vs NEW challenge (R10) ---
        www_auth2 = (
            resp_headers2.get("WWW-Authenticate") or resp_headers2.get("www-authenticate", "")
        )
        self._handle_post_pay_402(url, www_auth, www_auth2)

        # We got here: new challenge, within re-pay cap — pay again.
        auth_value2 = self.handle_challenge(url, www_auth2, sats=sats)
        cached_now2 = self._store.get(_parse_challenge(www_auth2).scope_key)
        preimage_used2 = cached_now2.preimage if cached_now2 else None

        request_headers["Authorization"] = auth_value2
        status3, resp_headers3, resp_body3 = fetcher(url, method, request_headers, body)

        if status3 == 402:
            raise RepayCapExceeded(
                f"Resource at {url!r} returned 402 three times in one fetch cycle. "
                "Refusing to continue to avoid runaway spending."
            )

        return FetchResult(
            status=status3,
            body=resp_body3,
            headers=resp_headers3,
            paid_sats=paid_sats + sats,
            cached=False,
            preimage_used=preimage_used2,
        )

    # ------------------------------------------------------------------
    # Post-pay 402 classification (R10)
    # ------------------------------------------------------------------

    def _handle_post_pay_402(
        self,
        url: str,
        original_www_auth: str,
        new_www_auth: str,
    ) -> None:
        """Classify the post-pay 402 as SAME or NEW challenge and enforce cap.

        - SAME challenge (same macaroon + same invoice): token was rejected
          (clock skew, server-side invalidation).  Do NOT re-pay — raise.
        - NEW challenge (different macaroon or different invoice): a new toll
          gate.  Enforce ``max_repays_per_resource_window`` then allow.
        """
        # Parse both challenges (invalid ones raise here — good, fail closed).
        orig = _parse_challenge(original_www_auth)
        new = _parse_challenge(new_www_auth)

        orig_fp = f"{orig.macaroon_b64}|{orig.invoice}"
        new_fp = f"{new.macaroon_b64}|{new.invoice}"

        if orig_fp == new_fp:
            # SAME challenge — the token we just paid for was rejected.
            # Could be clock skew or server-side invalidation.  Do NOT re-pay.
            self._audit("post_pay_same_challenge", url=url)
            raise RepayCapExceeded(
                f"Post-pay 402 on {url!r} carried the SAME challenge (same macaroon "
                "and invoice) as the one just paid.  This indicates the token was "
                "rejected server-side (clock skew? revoked?).  Refusing to re-pay "
                "the same invoice to avoid a double-spend."
            )

        # NEW challenge — check re-pay cap.
        rec = self._repay.setdefault(url, _RepayRecord())
        rec.count += 1
        rec.last_challenge_fingerprint = new_fp

        cap = self._config.max_repays_per_resource_window
        if rec.count > cap:
            self._audit("repay_cap_exceeded", url=url, count=rec.count, cap=cap)
            raise RepayCapExceeded(
                f"Resource at {url!r} has triggered {rec.count} re-pays in the current "
                f"window, exceeding the cap of {cap}.  Refusing to continue."
            )

        self._audit("post_pay_new_challenge", url=url, count=rec.count, cap=cap)

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def _guard_domain(self, url: str, challenge: ParsedChallenge) -> None:
        """Check allowed_domains and denied_domains lists."""
        cfg = self._config
        if not cfg.denied_domains and not cfg.allowed_domains:
            return
        try:
            host = urlparse(url).hostname or ""
        except Exception:  # noqa: BLE001
            host = ""

        if cfg.denied_domains:
            for pattern in cfg.denied_domains:
                if host == pattern or host.endswith("." + pattern):
                    self._audit("refused_denied_domain", url=url, host=host, pattern=pattern)
                    raise PaymentRejected(
                        f"Domain {host!r} is in the denied_domains list. Payment refused."
                    )

        if cfg.allowed_domains:
            allowed = any(
                host == p or host.endswith("." + p) for p in cfg.allowed_domains
            )
            if not allowed:
                self._audit("refused_not_in_allowed_domains", url=url, host=host)
                raise PaymentRejected(
                    f"Domain {host!r} is not in the allowed_domains list. Payment refused."
                )

    def _guard_cap_and_approval(
        self,
        url: str,
        challenge: ParsedChallenge,
        sats: int,
    ) -> None:
        """Enforce max_auto_pay_sats and the approval callback."""
        cfg = self._config
        if cfg.max_auto_pay_sats is not None and sats > cfg.max_auto_pay_sats:
            # Try approval callback before refusing.
            if cfg.approve is not None and cfg.approve(challenge):
                self._audit(
                    "approved_over_cap",
                    url=url,
                    sats=sats,
                    cap=cfg.max_auto_pay_sats,
                )
                return
            self._audit(
                "refused_over_cap",
                url=url,
                sats=sats,
                cap=cfg.max_auto_pay_sats,
            )
            raise PaymentRejected(
                f"Payment of {sats} sats exceeds max_auto_pay_sats={cfg.max_auto_pay_sats}. "
                "Payment refused. Supply an `approve` callback to override."
            )

    # ------------------------------------------------------------------
    # Preimage validation
    # ------------------------------------------------------------------

    @staticmethod
    def _check_preimage(result: PaidResult) -> None:
        """Raise PreimageError if the payer returned a faulted or missing preimage."""
        if result.preimage_error:
            raise PreimageError(
                f"Payer returned a preimage_error: {result.preimage_error!r}. "
                "Cannot build an L402 Authorization header without a valid preimage."
            )
        if not result.preimage:
            raise PreimageError(
                "Payer returned no preimage (null/empty). "
                "Cannot build an L402 Authorization header without a preimage. "
                "Ensure the Conduit pay endpoint returns a preimage "
                "(requires write-scoped API key and a settled payment)."
            )

    # ------------------------------------------------------------------
    # Audit sink
    # ------------------------------------------------------------------

    def _audit(self, event: str, **kwargs: Any) -> None:
        if self._config.audit is not None:
            try:
                self._config.audit({"event": event, **kwargs})
            except Exception:  # noqa: BLE001
                pass  # audit errors must never break the payment path


# ---------------------------------------------------------------------------
# Convenience: build a payer callable from a conduit.Agent (optional helper)
# ---------------------------------------------------------------------------


def agent_payer(agent: Any, sats: int | None = None) -> Callable[[str, int], PaidResult]:
    """Build a ``pay_invoice`` callable wrapping a ``conduit.Agent``.

    Usage::

        from conduit import Agent
        from conduit.l402 import L402Engine, L402Config, agent_payer

        engine = L402Engine(pay_invoice=agent_payer(my_agent))

    The returned callable ignores the ``sats`` parameter on the callable
    (uses the amount encoded in the invoice when the invoice is self-describing,
    or the passed-in ``sats`` for zero-amount invoices).
    """

    def _pay(invoice: str, pay_sats: int) -> PaidResult:
        receipt = agent.pay(to=invoice, sats=pay_sats)
        return PaidResult(preimage=receipt.preimage, preimage_error=receipt.preimage_error)

    return _pay


__all__ = [
    # Errors
    "L402Error",
    "InvalidChallenge",
    "UnsupportedChallenge",
    "PaymentRejected",
    "RepayCapExceeded",
    "PreimageError",
    # Protocol enum
    "Protocol",
    # Data containers
    "PaidResult",
    "ParsedChallenge",
    "CachedToken",
    "FetchResult",
    # Config
    "L402Config",
    # Store
    "TokenStore",
    # Engine
    "L402Engine",
    # Convenience
    "agent_payer",
]
