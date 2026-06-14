"""Regression: conduit_pay destination routing.

`_looks_like_pubkey` decides whether a `to` is a bare node pubkey (→ keysend)
or a Lightning address / BOLT11 invoice (→ the address/invoice path). A MALFORMED
pubkey must NOT match here — it falls through to the invoice path, which rejects
it as INVALID_INPUT before any debit (so the stranded-funds protection holds).
"""
from conduit_mcp.server import _looks_like_pubkey

VALID_PUBKEY = "02001bbe134990961c76e0d31386b3db6253f299da17bc53ffde2f9ac10214c0c0"


def test_valid_compressed_pubkey_routes_to_keysend():
    assert _looks_like_pubkey(VALID_PUBKEY) is True
    assert _looks_like_pubkey("03" + "ab" * 32) is True  # 03 prefix too
    assert _looks_like_pubkey("  " + VALID_PUBKEY + "  ") is True  # tolerant of whitespace


def test_lightning_address_is_not_a_pubkey():
    assert _looks_like_pubkey("alice@example.com") is False
    assert _looks_like_pubkey("compute-node-7@lnd.example.com") is False


def test_bolt11_is_not_a_pubkey():
    assert _looks_like_pubkey("lnbc10u1p4zau6r...") is False
    assert _looks_like_pubkey("lnbcrt15u1p4zau54pp5...") is False


def test_malformed_pubkey_does_not_match():
    assert _looks_like_pubkey("deadbeef") is False          # too short
    assert _looks_like_pubkey("04" + "aa" * 32) is False    # wrong prefix (not 02/03)
    assert _looks_like_pubkey("02" + "zz" * 32) is False    # 66 chars but not hex
    assert _looks_like_pubkey("02" + "ab" * 31) is False    # 64 chars, one short
    assert _looks_like_pubkey("") is False
