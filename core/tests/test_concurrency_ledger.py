"""Concurrency regression test for the per-agent balance ledger.

Reproduces a lost-update race found by the Phase-4 regtest stress test: many
DISTINCT concurrent payments to the SAME agent drifted `balance_sats` away from
the transaction ledger (in both directions, non-deterministically). Root cause:
the settle (Phase 3b) and failure-refund (Phase 3a) paths re-`SELECT ... FOR
UPDATE`-ed the agent, but with `expire_on_commit=False` the session returned the
stale identity-map object (still holding the pre-concurrency Phase-1 balance) and
wrote it back, clobbering other in-flight payments. Fixed with
`populate_existing=True` on those re-selects.

Earlier concurrency tests never caught it because they reused the SAME
idempotency key, so only ONE payment actually executed. This fires distinct
payments so they all run.
"""

import asyncio

import pytest

from conduit_core.config import get_settings

pytestmark = pytest.mark.asyncio

# This race is mediated by SELECT ... FOR UPDATE row locking, which only exists on
# Postgres. SQLite (dev/test) has no row locking — concurrent read-modify-writes
# race regardless of the fix — and Postgres is the ONLY supported production DB
# (the config validator refuses to boot on SQLite in prod). So this test is
# meaningful only on Postgres; it runs in CI's `core-postgres` job.
_IS_POSTGRES = get_settings().database_url.startswith("postgresql")

_DEST = "02" + "aa" * 32  # 66-hex keysend destination the mock LND settles


async def _create_agent(client, name: str) -> str:
    r = await client.post("/v1/agents", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _credit(client, agent_id: str, sats: int) -> None:
    r = await client.post(
        f"/v1/agents/{agent_id}/credit", json={"sats": sats, "reason": "test setup"}
    )
    assert r.status_code == 201, r.text


def _ledger_debited(txs: list[dict]) -> int:
    """Sum of what every non-failed send removed from the balance."""
    return sum(
        t["amount_sats"] + t["fee_sats"] + t.get("platform_fee_sats", 0)
        for t in txs
        if t["direction"] == "send" and t["status"] in ("settled", "pending")
    )


@pytest.mark.skipif(
    not _IS_POSTGRES,
    reason="row-locked concurrency (SELECT FOR UPDATE) is only enforced on Postgres; "
    "SQLite has no row locking and is not a supported production database",
)
async def test_concurrent_distinct_payments_keep_balance_consistent(client):
    """`balance_sats` must always reconcile with the transaction ledger, even
    under many distinct concurrent payments to one agent."""
    agent_id = await _create_agent(client, "concurrency-ledger")
    credited = 100_000
    await _credit(client, agent_id, credited)

    n = 25
    payloads = [
        {"agent_id": agent_id, "dest_pubkey": _DEST, "sats": 200, "memo": f"conc-{i}"}
        for i in range(n)
    ]
    results = await asyncio.gather(
        *(client.post("/v1/payments/send", json=p) for p in payloads)
    )
    codes = [r.status_code for r in results]
    # Ample balance + mock LND → every distinct payment settles; never a 5xx.
    assert all(c in (200, 201) for c in codes), codes

    bal = (await client.get(f"/v1/agents/{agent_id}/balance")).json()
    txs = (
        await client.get(f"/v1/agents/{agent_id}/transactions?limit=500")
    ).json()["data"]
    debited = _ledger_debited(txs)

    # THE INVARIANT: the denormalized balance equals credited minus the exact
    # sum of the transaction ledger. A lost-update race breaks this.
    assert bal["available_sats"] == credited - debited, (
        f"ledger drift under concurrency: balance={bal['available_sats']} != "
        f"credited({credited}) - ledger_debited({debited}) = {credited - debited}"
    )
    # And the balance must never be impossible.
    assert bal["available_sats"] >= 0


@pytest.mark.skipif(
    not _IS_POSTGRES,
    reason="overspend protection relies on SELECT ... FOR UPDATE row locking, "
    "only enforced on Postgres",
)
async def test_concurrent_payments_cannot_overspend(client):
    """Audit H7: N payments that each individually pass the balance check but
    together exceed the balance — exactly N-1 settle, 1 gets 402, never overspend.
    sats=100 so fee_budget (1) == actual mock fee (1): no fee refund frees balance,
    making the cutoff deterministic. debit_total = 100 + 1 fee + 1 platform = 102."""
    agent_id = await _create_agent(client, "overspend-race")
    n = 20
    debit_total = 102
    credited = n * debit_total - 1  # room for exactly n-1
    await _credit(client, agent_id, credited)

    payloads = [
        {"agent_id": agent_id, "dest_pubkey": _DEST, "sats": 100, "memo": f"os-{i}"}
        for i in range(n)
    ]
    results = await asyncio.gather(
        *(client.post("/v1/payments/send", json=p) for p in payloads)
    )
    codes = [r.status_code for r in results]
    ok = [r for r in results if r.status_code in (200, 201)]
    rejected = [r for r in results if r.status_code == 402]
    assert len(ok) == n - 1, f"expected {n - 1} settled, got {len(ok)}: {codes}"
    assert len(rejected) == 1, f"expected exactly 1 overdraft 402: {codes}"
    assert rejected[0].json()["detail"]["code"] == "INSUFFICIENT_BALANCE"

    bal = (await client.get(f"/v1/agents/{agent_id}/balance")).json()
    txs = (
        await client.get(f"/v1/agents/{agent_id}/transactions?limit=500")
    ).json()["data"]
    assert bal["available_sats"] == credited - _ledger_debited(txs)
    assert bal["available_sats"] >= 0  # the invariant: never overspent


@pytest.mark.skipif(
    not _IS_POSTGRES,
    reason="the treasury ledger advisory lock (pg_advisory_xact_lock) is a no-op on "
    "SQLite; the withdraw TOCTOU it prevents is only testable on Postgres",
)
async def test_concurrent_withdrawals_cannot_breach_solvency(client):
    """Audit H8: two /treasury/withdraw each within headroom but together breaching
    solvency — exactly one succeeds, the other 422s on the guard. Without the
    advisory lock both would read the same pre-send assets and over-withdraw."""
    from conduit_core.services.lnd import MockLNDClient, _MockState, get_lnd

    lnd = get_lnd()
    if isinstance(lnd, MockLNDClient):
        lnd._state = _MockState()  # assets = 5M on-chain + 5M channel = 10M

    # Liabilities = 9.9M so withdrawable headroom (~92k after reserve) fits ONE
    # 60k withdrawal but not two.
    agent_id = await _create_agent(client, "withdraw-toctou")
    await _credit(client, agent_id, 9_900_000)
    addr = "bcrt1qtoctoptest00000000000000"
    body = {"amount_sats": 60_000, "address": addr}
    r1, r2 = await asyncio.gather(
        client.post("/v1/treasury/withdraw", json=body, headers={"Idempotency-Key": "toctou-a"}),
        client.post("/v1/treasury/withdraw", json=body, headers={"Idempotency-Key": "toctou-b"}),
    )
    codes = sorted([r1.status_code, r2.status_code])
    assert codes == [201, 422], (
        f"expected one success + one solvency-422, got {codes}: {r1.text} | {r2.text}"
    )
