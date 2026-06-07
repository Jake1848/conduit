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
