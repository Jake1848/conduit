"""U1 — payment preimage exposure + integrity verification.

Covers the three-state contract of `verify_preimage` (absent / verified /
integrity-fault) at the unit level, and its exposure through the API. The
preimage is a bearer proof-of-payment secret, so it is returned ONLY in the
synchronous write-scoped pay/send response — never on a read-scoped GET/list
surface (those carry the non-secret `preimage_error` only). These tests pin
both the verification contract and that disclosure boundary.
"""

import hashlib
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from conduit_core.services.preimage import verify_preimage

from .conftest import credit_agent


def _hash_of(preimage_hex: str) -> str:
    return hashlib.sha256(bytes.fromhex(preimage_hex)).hexdigest()


# --------------------------------------------------------------------------- #
# Unit: the three-state verifier
# --------------------------------------------------------------------------- #


def test_verify_preimage_verified():
    pre = "11" * 32
    got, err = verify_preimage(pre, _hash_of(pre))
    assert got == pre
    assert err is None


def test_verify_preimage_verified_uppercase_stored_hash():
    # A payment_hash stored uppercase must still verify (case-normalized).
    pre = "ab" * 32
    got, err = verify_preimage(pre, _hash_of(pre).upper())
    assert got == pre
    assert err is None


def test_verify_preimage_absent_is_not_a_fault():
    # State 1: no preimage. Both None — absence, not failure.
    assert verify_preimage(None, "bb" * 32) == (None, None)
    assert verify_preimage("", "bb" * 32) == (None, None)


def test_verify_preimage_hash_mismatch_is_surfaced(monkeypatch):
    # State 3: a preimage IS present but does not hash to the payment_hash.
    calls = []
    monkeypatch.setattr(
        "conduit_core.services.preimage.record_preimage_integrity_fault",
        lambda: calls.append(1),
    )
    got, err = verify_preimage("11" * 32, "bb" * 32)
    assert got is None  # never exposed
    assert err == "hash_mismatch"  # surfaced, not nulled-as-absent
    assert calls == [1]  # metered


def test_verify_preimage_missing_hash_is_surfaced(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "conduit_core.services.preimage.record_preimage_integrity_fault",
        lambda: calls.append(1),
    )
    got, err = verify_preimage("11" * 32, None)
    assert got is None
    assert err == "missing_payment_hash"
    assert calls == [1]


def test_verify_preimage_malformed_is_surfaced(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "conduit_core.services.preimage.record_preimage_integrity_fault",
        lambda: calls.append(1),
    )
    got, err = verify_preimage("not-hex!!", "bb" * 32)
    assert got is None
    assert err == "malformed_preimage"
    assert calls == [1]


def test_verify_preimage_wrong_length_is_malformed(monkeypatch):
    # Valid hex but not 32 bytes — rejected early as malformed (defense-in-depth).
    monkeypatch.setattr(
        "conduit_core.services.preimage.record_preimage_integrity_fault",
        lambda: None,
    )
    short = "1122"  # 2 bytes
    got, err = verify_preimage(short, _hash_of(short))
    assert got is None
    assert err == "malformed_preimage"


# --------------------------------------------------------------------------- #
# API: happy path — the WRITE-scoped pay/send response exposes a verifying
# preimage; the READ-scoped GET does not (it is a bearer secret).
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_pay_response_exposes_preimage_but_read_get_does_not(client: AsyncClient):
    agent_id = (
        await client.post("/v1/agents", json={"name": "l402-buyer", "daily_limit": 50_000})
    ).json()["id"]
    await credit_agent(client, agent_id, 100_000)

    r = await client.post(
        "/v1/payments/send",
        json={"agent_id": agent_id, "dest_pubkey": "02" + "be" * 32, "sats": 210},
    )
    assert r.status_code == 201, r.text
    receipt = r.json()

    # Write-scoped pay response: the payer gets the verifying preimage.
    assert receipt["status"] == "settled"
    assert receipt["preimage_error"] is None
    assert receipt["preimage"], "pay response must expose a preimage for L402"
    assert _hash_of(receipt["preimage"]) == receipt["hash"]

    # Read-scoped GET of the same payment: the bearer secret is NOT disclosed.
    got = (await client.get(f"/v1/payments/{receipt['id']}")).json()
    assert got["preimage"] is None, "read-scoped GET must not leak the preimage secret"
    assert got["preimage_error"] is None

    # Read-scoped transaction surface: no preimage field at all.
    tx = (await client.get(f"/v1/transactions/{receipt['id']}")).json()
    assert "preimage" not in tx, "transaction surface must not carry the preimage secret"
    assert tx["preimage_error"] is None


@pytest.mark.asyncio
async def test_pay_response_surfaces_integrity_fault(client: AsyncClient, monkeypatch):
    """If LND hands back a preimage that does not hash to payment_hash, the
    write-scoped pay response must surface preimage_error and withhold the
    preimage — proving the state-3 path end-to-end on the one surface that
    actually returns the secret (the mock can't produce this naturally)."""
    from conduit_core.services.lnd import PaymentResult, get_lnd

    faults = []
    monkeypatch.setattr(
        "conduit_core.services.preimage.record_preimage_integrity_fault",
        lambda: faults.append(1),
    )

    async def _mismatched_keysend(*a, **kw):
        return PaymentResult(
            payment_hash="bb" * 32,
            payment_preimage="11" * 32,  # sha256(11*32) != bb*32
            amount_sats=210,
            fee_sats=1,
            latency_ms=10,
            status="settled",
        )

    monkeypatch.setattr(get_lnd(), "keysend", _mismatched_keysend)

    agent_id = (
        await client.post("/v1/agents", json={"name": "fault-buyer", "daily_limit": 50_000})
    ).json()["id"]
    await credit_agent(client, agent_id, 100_000)

    r = await client.post(
        "/v1/payments/send",
        json={"agent_id": agent_id, "dest_pubkey": "02" + "be" * 32, "sats": 210},
    )
    assert r.status_code == 201, r.text
    receipt = r.json()
    assert receipt["preimage"] is None  # withheld
    assert receipt["preimage_error"] == "hash_mismatch"  # surfaced
    assert faults == [1]  # metered via the live route path


# --------------------------------------------------------------------------- #
# API: integrity fault (state 3) on the read surfaces — preimage_error is
# surfaced (and metered), the secret is never present.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_corrupt_preimage_surfaces_error_without_leaking(client: AsyncClient, monkeypatch):
    """A stored preimage that does not hash to payment_hash must report
    preimage_error on the read surfaces and meter the fault — without ever
    exposing the preimage. Inject the bad row directly."""
    from conduit_core.db.database import SessionLocal
    from conduit_core.db.models import Transaction

    faults = []
    monkeypatch.setattr(
        "conduit_core.services.preimage.record_preimage_integrity_fault",
        lambda: faults.append(1),
    )

    agent_id = (
        await client.post("/v1/agents", json={"name": "corrupt-row", "daily_limit": 1})
    ).json()["id"]

    bad_tx_id = "tx_integrity_fault_u1"
    async with SessionLocal() as s:
        s.add(
            Transaction(
                id=bad_tx_id,
                agent_id=agent_id,
                direction="send",
                amount_sats=210,
                status="settled",
                payment_hash="bb" * 32,
                payment_preimage="11" * 32,  # sha256(11*32) != bb*32
                settled_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
            )
        )
        await s.commit()

    pay = (await client.get(f"/v1/payments/{bad_tx_id}")).json()
    assert pay["preimage"] is None
    assert pay["preimage_error"] == "hash_mismatch"

    tx = (await client.get(f"/v1/transactions/{bad_tx_id}")).json()
    assert "preimage" not in tx
    assert tx["preimage_error"] == "hash_mismatch"

    assert faults, "integrity fault must be metered via the API path"


# --------------------------------------------------------------------------- #
# API: absent preimage (state 1) is not a fault — pending send and settled
# receive (invoices never store a preimage).
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "direction,status",
    [("send", "pending"), ("receive", "settled")],
)
async def test_absent_preimage_is_not_a_fault(
    client: AsyncClient, direction: str, status: str
):
    from conduit_core.db.database import SessionLocal
    from conduit_core.db.models import Transaction

    agent_id = (
        await client.post("/v1/agents", json={"name": f"absent-{direction}", "daily_limit": 1})
    ).json()["id"]

    tx_id = f"tx_absent_{direction}_{status}"
    async with SessionLocal() as s:
        s.add(
            Transaction(
                id=tx_id,
                agent_id=agent_id,
                direction=direction,
                amount_sats=210,
                status=status,
                payment_hash="bb" * 32,
                payment_preimage=None,
                settled_at=datetime.now(UTC) if status == "settled" else None,
                created_at=datetime.now(UTC),
            )
        )
        await s.commit()

    tx = (await client.get(f"/v1/transactions/{tx_id}")).json()
    assert "preimage" not in tx
    assert tx["preimage_error"] is None  # absent, NOT a fault
