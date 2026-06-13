"""Regression tests for the pre-launch audit fixes (Phase 1)."""
import pytest

from conduit_core.errors import LNDError, PaymentFailed
from conduit_core.services.lnd import LNDRestClient

# ---- H1: empty/UNKNOWN LND result must NOT be a refundable failure ----

def test_parse_payment_only_explicit_failed_is_refundable():
    # _parse_payment doesn't touch self; call it unbound with a dummy self.
    parse = LNDRestClient._parse_payment

    # Explicit terminal FAILED -> PaymentFailed (route Phase 3a refunds — safe).
    with pytest.raises(PaymentFailed):
        parse(None, {"status": "FAILED", "failure_reason": "NO_ROUTE"}, 0.0)

    # Empty / UNKNOWN / IN_FLIGHT / missing -> LNDError (route Phase 3c: NO refund,
    # needs_reconciliation). Refunding any of these could double-spend.
    for data in ({}, {"status": "UNKNOWN"}, {"status": "IN_FLIGHT"}, {"status": ""}):
        with pytest.raises(LNDError):
            parse(None, data, 0.0)
        # critically, NOT the refundable type:
        try:
            parse(None, data, 0.0)
        except PaymentFailed:  # pragma: no cover
            pytest.fail(f"{data} wrongly raised PaymentFailed (would refund)")
        except LNDError:
            pass

    # SUCCEEDED -> a real settled result.
    r = parse(
        None,
        {
            "status": "SUCCEEDED",
            "payment_hash": "abcd",
            "payment_preimage": "ef01",
            "value_sat": 100,
            "fee_sat": 1,
        },
        0.0,
    )
    assert r.status == "settled" and r.amount_sats == 100 and r.fee_sats == 1


# ---- M3: /v1/metrics hides operator liquidity/revenue from a read key ----

@pytest.mark.asyncio
async def test_metrics_hides_liquidity_from_read_key(client):
    a = (await client.post("/v1/agents", json={"name": "m3"})).json()["id"]
    await client.post(f"/v1/agents/{a}/credit", json={"sats": 5000})
    admin = (await client.get("/v1/metrics")).json()
    assert admin["treasury_sats"] >= 5000  # admin sees operator liquidity

    rk = (
        await client.post("/v1/api-keys", json={"scope": "read", "label": "m3"})
    ).json()["secret"]
    read = (await client.get("/v1/metrics", headers={"Authorization": f"Bearer {rk}"})).json()
    assert read["treasury_sats"] == 0  # read key does NOT
    assert read["fee_revenue_total_sats"] == 0
    assert read["solvency_ratio"] is None
    assert read["active_agents"] == admin["active_agents"]  # fleet counters stay readable


# ---- M4: deeply-nested JSON -> 422 not 500 ----

@pytest.mark.asyncio
async def test_deep_nested_json_is_422(client):
    body = '{"name": ' + "[" * 2000 + "1" + "]" * 2000 + ', "daily_limit": 1}'
    r = await client.post(
        "/v1/agents", content=body, headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 422, f"{r.status_code}: deep JSON must be 422, not 500"


# ---- M5: webhook URL null byte -> 422 not 500 ----

@pytest.mark.asyncio
async def test_webhook_url_null_byte_is_422(client):
    r = await client.post(
        "/v1/webhooks",
        json={"url": "https://hooks.example.com/\x00evil", "events": ["payment.settled"]},
    )
    assert r.status_code == 422, r.text
