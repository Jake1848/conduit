"""Validate a stored Lightning payment preimage before exposing it via the API.

L402 clients need the payment preimage to build the `Authorization: L402
<macaroon>:<preimage>` header. Conduit captures and stores the preimage on
settle; this helper is the gate that decides whether a stored value is safe to
return.

The three states are deliberately distinct — conflating "no preimage" with
"preimage failed verification" would hide a real server bug and hand clients a
token that silently never works:

  1. No preimage exists yet (pending / failed / keysend without a known
     preimage)               -> (None, None)            — legitimately absent.
  2. Preimage verifies
     (sha256(preimage) == payment_hash) -> (<hex>, None) — safe to expose.
  3. A preimage IS stored but does NOT verify (malformed, missing hash, or a
     mismatch from corruption / an LND edge state / a reconciler bug)
                              -> (None, "<reason>")      — a server-side
     integrity fault: surfaced (never nulled-as-absent), logged at error level,
     and metered.
"""

import hashlib

import structlog

from ..observability import record_preimage_integrity_fault

log = structlog.get_logger(__name__)


def verify_preimage(
    preimage: str | None, payment_hash: str | None
) -> tuple[str | None, str | None]:
    """Return (preimage, error) per the three-state contract above.

    `preimage` is non-None only when it verifies against `payment_hash`.
    `error` is non-None only for an integrity fault (state 3); its presence is
    how a caller tells "failed to verify" apart from "absent".
    """
    if not preimage:
        return None, None

    if not payment_hash:
        # A preimage with nothing to check it against — we cannot vouch for it.
        log.error("preimage_integrity_fault", reason="missing_payment_hash")
        record_preimage_integrity_fault()
        return None, "missing_payment_hash"

    try:
        raw = bytes.fromhex(preimage)
    except ValueError:
        log.error("preimage_integrity_fault", reason="malformed_preimage")
        record_preimage_integrity_fault()
        return None, "malformed_preimage"

    # A Lightning preimage is exactly 32 bytes. Reject anything else early as a
    # malformed value rather than hashing it (defense-in-depth).
    if len(raw) != 32:
        log.error("preimage_integrity_fault", reason="malformed_preimage")
        record_preimage_integrity_fault()
        return None, "malformed_preimage"

    derived = hashlib.sha256(raw).hexdigest()

    if derived.lower() != payment_hash.lower():
        log.error(
            "preimage_integrity_fault",
            reason="hash_mismatch",
            payment_hash=payment_hash,
        )
        record_preimage_integrity_fault()
        return None, "hash_mismatch"

    return preimage, None
