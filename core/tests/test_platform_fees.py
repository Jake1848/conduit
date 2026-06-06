"""Platform fee engine — the self-hosted operator's per-payment revenue.

Invariants:
- charged ON TOP of payment + routing budget, recorded on the tx and the receipt
- KEPT on a settled payment (revenue), REFUNDED in full on a failed one
- surfaced via GET /v1/fees and folded into GET /v1/metrics
"""

import pytest

from conduit_core.services.fees import compute_platform_fee

# ---------- pure fee calculation ----------


def test_compute_platform_fee_standard():
    assert compute_platform_fee(1000, 0.5, 1, 1000) == 5
    assert compute_platform_fee(10_000, 0.5, 1, 1000) == 50


def test_compute_platform_fee_floor():
    # 100 * 0.5% = 0.5 → rounds toward 0 → the min floor applies.
    assert compute_platform_fee(100, 0.5, 1, 1000) == 1


def test_compute_platform_fee_cap():
    # 1_000_000 * 0.5% = 5000, capped at max.
    assert compute_platform_fee(1_000_000, 0.5, 1, 1000) == 1000


def test_compute_platform_fee_disabled():
    assert compute_platform_fee(1000, 0.0, 1, 1000) == 0
    assert compute_platform_fee(1000, -1.0, 1, 1000) == 0


def test_compute_platform_fee_zero_amount():
    assert compute_platform_fee(0, 0.5, 1, 1000) == 0


def test_compute_platform_fee_misconfigured_min_gt_max():
    # Cap always wins so a fat-fingered min can't overcharge.
    assert compute_platform_fee(1000, 0.5, 9999, 10) == 10


# ---------- end-to-end through the payment flow ----------


async def _agent_with_balance(client, name: str, sats: int) -> str:
    aid = (await client.post("/v1/agents", json={"name": name})).json()["id"]
    r = await client.post(f"/v1/agents/{aid}/credit", json={"sats": sats, "reason": "t"})
    assert r.status_code == 201, r.text
    return aid


@pytest.mark.asyncio
async def test_settled_payment_charges_and_keeps_fee(client):
    aid = await _agent_with_balance(client, "fee-agent", 100_000)
    r = await client.post(
        "/v1/payments/send",
        json={"agent_id": aid, "dest_pubkey": "02" + "ab" * 32, "sats": 1000},
    )
    assert r.status_code == 201, r.text
    receipt = r.json()
    # 1000 * 0.5% = 5 platform fee; mock routing fee for 1000 sats = 1.
    assert receipt["platform_fee_sats"] == 5
    assert receipt["fee_sats"] == 1

    # Balance reflects amount + actual routing + platform fee, none of the platform
    # fee refunded.
    bal = (await client.get(f"/v1/agents/{aid}/balance")).json()["available_sats"]
    assert bal == 100_000 - 1000 - receipt["fee_sats"] - receipt["platform_fee_sats"]

    # The fee is persisted on the transaction and visible on read-back.
    got = (await client.get(f"/v1/payments/{receipt['id']}")).json()
    assert got["platform_fee_sats"] == 5

    # ...and surfaces in the transaction listing, not just the receipt.
    txns = (await client.get(f"/v1/agents/{aid}/transactions?direction=send")).json()["data"]
    assert txns[0]["platform_fee_sats"] == 5


@pytest.mark.asyncio
async def test_failed_payment_refunds_platform_fee(client):
    # Credit far above the mock's 5_000_000-sat channel; a 6M send fails in LND
    # AFTER the debit (Phase 3a), so the full debit — incl. platform fee — refunds.
    aid = await _agent_with_balance(client, "fee-refund", 10_000_000)
    r = await client.post(
        "/v1/payments/send",
        json={"agent_id": aid, "dest_pubkey": "02" + "cd" * 32, "sats": 6_000_000},
    )
    assert r.status_code in (402, 502), r.text  # PaymentFailed
    bal = (await client.get(f"/v1/agents/{aid}/balance")).json()["available_sats"]
    assert bal == 10_000_000  # fully restored — no fee earned on a failed payment


@pytest.mark.asyncio
async def test_fees_endpoint_aggregates(client):
    aid = await _agent_with_balance(client, "fee-report", 100_000)
    for _ in range(3):
        r = await client.post(
            "/v1/payments/send",
            json={"agent_id": aid, "dest_pubkey": "02" + "ef" * 32, "sats": 1000},
        )
        assert r.status_code == 201, r.text

    fees = (await client.get("/v1/fees")).json()
    assert fees["total_collected_sats"] == 15  # 3 × 5
    assert fees["today_sats"] == 15
    assert fees["total_collected_btc"] == round(15 / 1e8, 8)
    assert fees["fees_by_day"], "expected at least one day bucket"
    today = fees["fees_by_day"][0]
    assert today["sats"] == 15
    assert today["tx_count"] == 3


@pytest.mark.asyncio
async def test_metrics_includes_fee_revenue(client):
    aid = await _agent_with_balance(client, "fee-metrics", 100_000)
    await client.post(
        "/v1/payments/send",
        json={"agent_id": aid, "dest_pubkey": "02" + "12" * 32, "sats": 2000},
    )
    m = (await client.get("/v1/metrics")).json()
    # 2000 * 0.5% = 10.
    assert m["fee_revenue_total_sats"] == 10
    assert m["fee_revenue_today_sats"] == 10


@pytest.mark.asyncio
async def test_fees_endpoint_requires_admin(client):
    # Mint a write-only key; it must NOT be able to read operator revenue.
    secret = (await client.post("/v1/api-keys", json={"scope": "write", "label": "w"})).json()[
        "secret"
    ]
    r = await client.get("/v1/fees", headers={"Authorization": f"Bearer {secret}"})
    assert r.status_code == 403, r.text
