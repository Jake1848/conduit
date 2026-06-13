"""Owner/admin treasury: revenue overview + on-chain withdrawal with a hard
solvency guard. Mock LND starts with 5,000,000 sats on-chain + 5,000,000 in
channels (assets = 10,000,000)."""
import pytest
import pytest_asyncio
from httpx import AsyncClient

WITHDRAW_ADDR = "bcrt1qtreasury000000000000000000"


@pytest_asyncio.fixture(autouse=True)
async def fresh_lnd():
    """The mock LND client is a process-level singleton whose balance is mutated
    by payments/withdrawals in other tests. Reset it to the default 5M on-chain +
    5M channel before each treasury test so the asset math is deterministic."""
    from conduit_core.services.lnd import MockLNDClient, _MockState, get_lnd

    lnd = get_lnd()
    if isinstance(lnd, MockLNDClient):
        lnd._state = _MockState()
    yield


async def _agent(client: AsyncClient, name: str) -> str:
    r = await client.post("/v1/agents", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _credit(client: AsyncClient, agent_id: str, sats: int) -> None:
    r = await client.post(f"/v1/agents/{agent_id}/credit", json={"sats": sats})
    assert r.status_code == 201, r.text


async def _read_key(client: AsyncClient) -> str:
    r = await client.post("/v1/api-keys", json={"scope": "read", "label": "t"})
    return r.json()["secret"]


# ---- Overview ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_overview_shape_and_withdrawable(client: AsyncClient):
    r = await client.get("/v1/treasury/overview")
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["assets_sats"] == 10_000_000
    assert o["onchain_confirmed_sats"] == 5_000_000
    assert o["agent_liabilities_sats"] == 0
    assert o["revenue_total_sats"] == 0
    # No liabilities -> bounded by on-chain confirmed minus the fee reserve.
    assert o["withdrawable_sats"] == 5_000_000 - o["fee_reserve_sats"]


@pytest.mark.asyncio
async def test_overview_reflects_revenue(client: AsyncClient):
    agent_id = await _agent(client, "rev")
    await _credit(client, agent_id, 100_000)
    r = await client.post(
        "/v1/payments/send",
        json={"agent_id": agent_id, "dest_pubkey": "02" + "ab" * 32, "sats": 5_000},
    )
    assert r.status_code == 201, r.text
    fee = r.json()["platform_fee_sats"]
    assert fee >= 1
    o = (await client.get("/v1/treasury/overview")).json()
    assert o["revenue_total_sats"] == fee


@pytest.mark.asyncio
async def test_overview_liabilities_lower_withdrawable(client: AsyncClient):
    agent_id = await _agent(client, "liab")
    await _credit(client, agent_id, 8_000_000)  # liabilities now 8M
    o = (await client.get("/v1/treasury/overview")).json()
    assert o["agent_liabilities_sats"] == 8_000_000
    # headroom = assets(10M) - liab(8M) - reserve(1000) = 1,999,000;
    # on-chain cap = 5M - 1000. min -> 1,999,000.
    assert o["withdrawable_sats"] == 2_000_000 - o["fee_reserve_sats"]
    assert o["solvent"] is True


# ---- Withdraw ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_withdraw_success(client: AsyncClient):
    before = (await client.get("/v1/treasury/overview")).json()
    r = await client.post(
        "/v1/treasury/withdraw", json={"amount_sats": 100_000, "address": WITHDRAW_ADDR}
    )
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["txid"] and out["amount_sats"] == 100_000
    assert out["withdrawal_id"].startswith("twd_")
    assert out["status"] == "broadcast"
    after = (await client.get("/v1/treasury/overview")).json()
    # On-chain dropped by amount + the mock's flat on-chain fee.
    assert after["onchain_confirmed_sats"] < before["onchain_confirmed_sats"] - 100_000 + 1
    # Durable BTC-transfer history reflects the broadcast.
    hist = after["recent_withdrawals"]
    assert len(hist) == 1
    assert hist[0]["txid"] == out["txid"]
    assert hist[0]["status"] == "broadcast"
    assert hist[0]["amount_sats"] == 100_000


@pytest.mark.asyncio
async def test_withdraw_fee_reserve_scales_with_rate(client: AsyncClient):
    # A high fee rate must enlarge the reserve (was a flat 1000-sat under-cushion).
    o = (await client.get("/v1/treasury/overview")).json()
    assert o["fee_reserve_sats"] >= 1000
    # Withdrawing right at the no-rate headroom but with a huge fee rate must be
    # rejected because the scaled reserve no longer fits.
    huge_rate = 9_000
    r = await client.post(
        "/v1/treasury/withdraw",
        json={"amount_sats": o["withdrawable_sats"], "address": WITHDRAW_ADDR,
              "sat_per_vbyte": huge_rate},
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_withdraw_blocked_by_solvency_guard(client: AsyncClient):
    agent_id = await _agent(client, "solv")
    await _credit(client, agent_id, 9_999_000)  # liabilities just under assets
    # withdrawable headroom is ~0; any real withdrawal breaches solvency.
    r = await client.post(
        "/v1/treasury/withdraw", json={"amount_sats": 50_000, "address": WITHDRAW_ADDR}
    )
    assert r.status_code == 422, r.text
    assert "solvency" in r.json()["detail"]["detail"].lower()


@pytest.mark.asyncio
async def test_withdraw_blocked_by_insufficient_onchain(client: AsyncClient):
    # Assets 10M (solvency fine, no liabilities) but on-chain confirmed is only 5M.
    r = await client.post(
        "/v1/treasury/withdraw", json={"amount_sats": 6_000_000, "address": WITHDRAW_ADDR}
    )
    assert r.status_code == 422, r.text
    assert "on-chain" in r.json()["detail"]["detail"].lower()


@pytest.mark.asyncio
async def test_withdraw_is_idempotent(client: AsyncClient):
    headers = {"Idempotency-Key": "withdraw-once"}
    body = {"amount_sats": 10_000, "address": WITHDRAW_ADDR}
    r1 = await client.post("/v1/treasury/withdraw", json=body, headers=headers)
    assert r1.status_code == 201, r1.text
    r2 = await client.post("/v1/treasury/withdraw", json=body, headers=headers)
    assert r2.status_code == 201, r2.text
    assert r2.json()["txid"] == r1.json()["txid"]  # same broadcast, not a second send
    assert r2.json()["withdrawal_id"] == r1.json()["withdrawal_id"]
    # Only ONE on-chain send happened (history has one row).
    hist = (await client.get("/v1/treasury/overview")).json()["recent_withdrawals"]
    assert len(hist) == 1


@pytest.mark.asyncio
async def test_withdraw_key_reuse_different_body_is_409(client: AsyncClient):
    headers = {"Idempotency-Key": "bound-key"}
    r1 = await client.post(
        "/v1/treasury/withdraw",
        json={"amount_sats": 10_000, "address": WITHDRAW_ADDR},
        headers=headers,
    )
    assert r1.status_code == 201, r1.text
    # Same key, DIFFERENT amount -> must not silently return the first withdrawal.
    r2 = await client.post(
        "/v1/treasury/withdraw",
        json={"amount_sats": 20_000, "address": WITHDRAW_ADDR},
        headers=headers,
    )
    assert r2.status_code == 409, r2.text


@pytest.mark.asyncio
async def test_withdraw_key_reusable_after_guard_failure(client: AsyncClient):
    # A guard failure records NOTHING, so the same key can be retried once the
    # request is valid (failures are self-healing, not cached as terminal).
    headers = {"Idempotency-Key": "retry-me"}
    r1 = await client.post(
        "/v1/treasury/withdraw",
        json={"amount_sats": 6_000_000, "address": WITHDRAW_ADDR},  # > on-chain
        headers=headers,
    )
    assert r1.status_code == 422, r1.text
    r2 = await client.post(
        "/v1/treasury/withdraw",
        json={"amount_sats": 100_000, "address": WITHDRAW_ADDR},  # now valid
        headers=headers,
    )
    assert r2.status_code == 201, r2.text


@pytest.mark.asyncio
async def test_withdraw_ambiguous_send_is_not_retryable_same_key(client: AsyncClient, monkeypatch):
    # BLOCKER regression (audit B1): a send_coins exception is AMBIGUOUS — the tx
    # may have broadcast (timeout after broadcast). It must terminalize to
    # `unknown`, and a SAME-KEY retry must 409 (NEVER re-broadcast → no
    # double-spend). The operator reconciles + uses a fresh key.
    from conduit_core.errors import LNDError
    from conduit_core.services.lnd import get_lnd

    lnd = get_lnd()
    calls = {"n": 0}

    async def always_raise(address, amount_sats, sat_per_vbyte=None):
        calls["n"] += 1
        raise LNDError("simulated ambiguous send failure (may have broadcast)")

    monkeypatch.setattr(lnd, "send_coins", always_raise)
    headers = {"Idempotency-Key": "ambiguous-send"}
    body = {"amount_sats": 30_000, "address": WITHDRAW_ADDR}
    r1 = await client.post("/v1/treasury/withdraw", json=body, headers=headers)
    assert r1.status_code == 502, r1.text  # LNDError -> 502
    # The durable record is `unknown`, not `failed`.
    hist = (await client.get("/v1/treasury/overview")).json()["recent_withdrawals"]
    assert hist and hist[0]["status"] == "unknown"
    # Same-key retry -> 409, and send_coins is NOT called a second time.
    r2 = await client.post("/v1/treasury/withdraw", json=body, headers=headers)
    assert r2.status_code == 409, r2.text
    assert calls["n"] == 1, "ambiguous send must never be re-broadcast under the same key"


@pytest.mark.asyncio
async def test_withdraw_in_progress_is_409(client: AsyncClient):
    from conduit_core.services import treasury as twd_svc

    # A genuinely in-flight (pending) withdrawal under a key -> retry gets 409.
    await twd_svc.record_pending(50_000, WITHDRAW_ADDR, None, 8000, "inflight-key")
    r = await client.post(
        "/v1/treasury/withdraw",
        json={"amount_sats": 50_000, "address": WITHDRAW_ADDR},
        headers={"Idempotency-Key": "inflight-key"},
    )
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_withdraw_succeeds_even_if_record_update_fails(client: AsyncClient, monkeypatch):
    # A post-broadcast bookkeeping failure must NOT turn a real spend into an
    # error response (the MEDIUM finding). mark_broadcast returning False (failed
    # update) still yields a 201 with the txid.
    from conduit_core.services import treasury as twd_svc

    async def _fail_mark(*a, **k):
        return False

    monkeypatch.setattr(twd_svc, "mark_broadcast", _fail_mark)
    r = await client.post(
        "/v1/treasury/withdraw", json={"amount_sats": 25_000, "address": WITHDRAW_ADDR}
    )
    assert r.status_code == 201, r.text
    assert r.json()["txid"]


# ---- Scope ----

@pytest.mark.asyncio
async def test_treasury_requires_admin(client: AsyncClient):
    secret = await _read_key(client)
    h = {"Authorization": f"Bearer {secret}"}
    assert (await client.get("/v1/treasury/overview", headers=h)).status_code == 403
    r = await client.post(
        "/v1/treasury/withdraw",
        json={"amount_sats": 1000, "address": WITHDRAW_ADDR},
        headers=h,
    )
    assert r.status_code == 403
