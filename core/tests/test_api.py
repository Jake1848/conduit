"""End-to-end smoke tests through the HTTP layer."""

import pytest


async def _credit(client, agent_id: str, sats: int) -> None:
    r = await client.post(
        f"/v1/agents/{agent_id}/credit", json={"sats": sats, "reason": "test setup"}
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_health_is_public(client):
    headers = {"Authorization": ""}
    r = await client.get("/v1/health", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "version" in body and "network" in body


@pytest.mark.asyncio
async def test_repeated_auth_updates_last_used_at(client):
    """Regression: auth writes api_keys.last_used_at = datetime.now(UTC) (tz-aware)
    on every authenticated request. With tz-naive columns this raised an asyncpg
    DataError on Postgres and 500'd every authenticated endpoint. Two back-to-back
    authenticated calls must both succeed. (Caught only when this suite runs against
    Postgres — see the `core-postgres` CI job.)"""
    r1 = await client.get("/v1/agents")
    assert r1.status_code == 200, r1.text
    r2 = await client.get("/v1/agents")
    assert r2.status_code == 200, r2.text


@pytest.mark.asyncio
async def test_status_requires_auth(client):
    r = await client.get("/v1/status", headers={"Authorization": ""})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_create_agent_attach_policy_and_pay(client):
    r = await client.post(
        "/v1/agents", json={"name": "compute-router-7", "daily_limit": 50_000}
    )
    assert r.status_code == 201, r.text
    agent = r.json()
    assert agent["name"] == "compute-router-7"
    agent_id = agent["id"]

    await _credit(client, agent_id, 100_000)

    r = await client.post(
        f"/v1/agents/{agent_id}/policy",
        json={"max_per_hour": 10_000, "allowlist": ["02" + "be" * 32]},
    )
    assert r.status_code == 201, r.text

    # Allowlist blocks unknown destinations.
    r = await client.post(
        "/v1/payments/send",
        json={
            "agent_id": agent_id,
            "dest_pubkey": "02" + "de" * 32,
            "sats": 150,
            "memo": "dataset query",
        },
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "DESTINATION_NOT_ALLOWLISTED"

    # Allowed destination succeeds (mock LND auto-settles).
    r = await client.post(
        "/v1/payments/send",
        json={
            "agent_id": agent_id,
            "dest_pubkey": "02" + "be" * 32,
            "sats": 150,
            "memo": "dataset query",
        },
    )
    assert r.status_code == 201, r.text
    receipt = r.json()
    assert receipt["status"] == "settled"
    assert receipt["amount_sats"] == 150
    assert receipt["settled_in_ms"] is not None
    assert receipt["hash"]

    # Balance was actually debited.
    bal = (await client.get(f"/v1/agents/{agent_id}/balance")).json()
    assert bal["available_sats"] < 100_000


@pytest.mark.asyncio
async def test_daily_limit_enforced_via_api(client):
    r = await client.post("/v1/agents", json={"name": "tight-budget", "daily_limit": 500})
    agent_id = r.json()["id"]
    await _credit(client, agent_id, 100_000)

    # First payment within limit succeeds.
    r = await client.post(
        "/v1/payments/send",
        json={
            "agent_id": agent_id,
            "dest_pubkey": "02" + "11" * 32,
            "sats": 400,
        },
    )
    assert r.status_code == 201, r.text

    # Second payment that would exceed the daily limit is denied.
    r = await client.post(
        "/v1/payments/send",
        json={
            "agent_id": agent_id,
            "dest_pubkey": "02" + "22" * 32,
            "sats": 200,
        },
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "DAILY_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_insufficient_balance_blocks_payment(client):
    r = await client.post("/v1/agents", json={"name": "broke"})
    agent_id = r.json()["id"]
    # No credit. balance is 0.

    r = await client.post(
        "/v1/payments/send",
        json={
            "agent_id": agent_id,
            "dest_pubkey": "02" + "ab" * 32,
            "sats": 100,
        },
    )
    assert r.status_code == 402, r.text
    assert r.json()["detail"]["code"] == "INSUFFICIENT_BALANCE"


@pytest.mark.asyncio
async def test_credit_and_debit_roundtrip(client):
    r = await client.post("/v1/agents", json={"name": "treasury"})
    agent_id = r.json()["id"]

    r = await client.post(
        f"/v1/agents/{agent_id}/credit", json={"sats": 5_000, "reason": "seed funding"}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["balance_sats"] == 5_000
    assert body["delta_sats"] == 5_000

    r = await client.post(
        f"/v1/agents/{agent_id}/debit", json={"sats": 2_000, "reason": "sweep"}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["balance_sats"] == 3_000
    assert body["delta_sats"] == -2_000

    bal = (await client.get(f"/v1/agents/{agent_id}/balance")).json()
    assert bal["available_sats"] == 3_000

    # Debit beyond balance is rejected.
    r = await client.post(
        f"/v1/agents/{agent_id}/debit", json={"sats": 10_000, "reason": "too much"}
    )
    assert r.status_code == 402, r.text
    assert r.json()["detail"]["code"] == "INSUFFICIENT_BALANCE"


@pytest.mark.asyncio
async def test_payment_failure_refunds_balance(client, monkeypatch):
    r = await client.post("/v1/agents", json={"name": "lnd-bork"})
    agent_id = r.json()["id"]
    await _credit(client, agent_id, 10_000)
    bal_before = (await client.get(f"/v1/agents/{agent_id}/balance")).json()["available_sats"]

    # Monkey-patch the mock LND to fail next keysend.
    from conduit_core.errors import PaymentFailed
    from conduit_core.services.lnd import get_lnd

    async def _boom(*a, **kw):
        raise PaymentFailed("simulated route failure")

    monkeypatch.setattr(get_lnd(), "keysend", _boom)

    r = await client.post(
        "/v1/payments/send",
        json={"agent_id": agent_id, "dest_pubkey": "02" + "cd" * 32, "sats": 500},
    )
    assert r.status_code == 502, r.text

    bal_after = (await client.get(f"/v1/agents/{agent_id}/balance")).json()["available_sats"]
    assert bal_after == bal_before, "balance must be fully refunded on payment failure"


@pytest.mark.asyncio
async def test_invoice_creation(client):
    r = await client.post("/v1/agents", json={"name": "receiver-1"})
    agent_id = r.json()["id"]
    r = await client.post(
        "/v1/invoices", json={"agent_id": agent_id, "amount": 5000, "memo": "service x"}
    )
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["amount_sats"] == 5000
    assert inv["payment_request"].startswith("ln")
    assert len(inv["payment_hash"]) >= 32

    r = await client.get(f"/v1/invoices/{inv['id']}")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_scope_denied_for_read_key_writing(client):
    r = await client.post(
        "/v1/api-keys", json={"scope": "read", "label": "read-only"}
    )
    assert r.status_code == 201
    read_key = r.json()["secret"]

    r = await client.get(
        "/v1/agents", headers={"Authorization": f"Bearer {read_key}"}
    )
    assert r.status_code == 200

    r = await client.post(
        "/v1/agents",
        json={"name": "should-fail"},
        headers={"Authorization": f"Bearer {read_key}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_unhandled_exception_returns_json_500(client, monkeypatch):
    """A crash inside a route handler should return our structured 500 JSON."""
    from conduit_core.services.lnd import get_lnd

    async def boom(*a, **kw):
        raise RuntimeError("kaboom from test")

    # /v1/status calls lnd.get_info(); raising a non-ConduitError there
    # propagates to the global exception handler.
    monkeypatch.setattr(get_lnd(), "get_info", boom)

    r = await client.get("/v1/status")
    assert r.status_code == 500, r.text
    body = r.json()
    assert body["detail"]["code"] == "INTERNAL_ERROR"
    assert "kaboom" not in body["detail"]["detail"], "internal error text must not leak"


@pytest.mark.asyncio
async def test_production_refuses_default_secret(monkeypatch):
    """Lifespan must SystemExit if production sees the dev API_SECRET_KEY."""
    from conduit_core.config import (
        DEFAULT_API_SECRET,
        Settings,
        reset_settings_cache,
    )

    monkeypatch.setenv("CONDUIT_ENV", "production")
    monkeypatch.setenv("CONDUIT_NETWORK", "mainnet")
    monkeypatch.setenv("API_SECRET_KEY", DEFAULT_API_SECRET)
    monkeypatch.setenv("BOOTSTRAP_API_KEY", "ck_live_test_for_assertion_xxxxxxxxxxxx")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x/y")
    reset_settings_cache()
    errs = Settings().validate_for_runtime()
    assert any("API_SECRET_KEY" in e for e in errs), errs
    reset_settings_cache()


@pytest.mark.asyncio
async def test_production_requires_postgres(monkeypatch):
    from conduit_core.config import Settings, reset_settings_cache

    monkeypatch.setenv("CONDUIT_ENV", "production")
    monkeypatch.setenv("CONDUIT_NETWORK", "mainnet")
    monkeypatch.setenv("API_SECRET_KEY", "x" * 64)
    monkeypatch.setenv("BOOTSTRAP_API_KEY", "ck_live_" + "x" * 32)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./conduit.db")
    reset_settings_cache()
    errs = Settings().validate_for_runtime()
    assert any("SQLite" in e for e in errs), errs
    reset_settings_cache()


@pytest.mark.asyncio
async def test_production_refuses_lnd_mock(monkeypatch):
    """A production boot against the MOCK LND must be rejected — the mock
    fabricates SUCCEEDED settlements and a solvent balance (phantom payouts)."""
    from conduit_core.config import Settings, reset_settings_cache

    monkeypatch.setenv("CONDUIT_ENV", "production")
    monkeypatch.setenv("CONDUIT_NETWORK", "mainnet")
    monkeypatch.setenv("API_SECRET_KEY", "x" * 64)
    monkeypatch.setenv("BOOTSTRAP_API_KEY", "ck_live_" + "x" * 32)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x/y")
    monkeypatch.setenv("LND_MOCK", "true")
    reset_settings_cache()
    errs = Settings().validate_for_runtime()
    assert any("LND_MOCK" in e for e in errs), errs
    reset_settings_cache()


@pytest.mark.asyncio
async def test_mainnet_refuses_lnd_mock_even_in_dev(monkeypatch):
    """Mainnet is real money regardless of CONDUIT_ENV — the mock is rejected
    even when CONDUIT_ENV is not 'production'."""
    from conduit_core.config import Settings, reset_settings_cache

    monkeypatch.setenv("CONDUIT_ENV", "development")
    monkeypatch.setenv("CONDUIT_NETWORK", "mainnet")
    monkeypatch.setenv("LND_MOCK", "true")
    reset_settings_cache()
    errs = Settings().validate_for_runtime()
    assert any("mainnet" in e and "LND_MOCK" in e for e in errs), errs
    reset_settings_cache()


@pytest.mark.asyncio
async def test_production_with_real_lnd_has_no_mock_error(monkeypatch):
    """The guard is specific: a correct production config (LND_MOCK=false) does
    NOT raise the LND_MOCK error."""
    from conduit_core.config import Settings, reset_settings_cache

    monkeypatch.setenv("CONDUIT_ENV", "production")
    monkeypatch.setenv("CONDUIT_NETWORK", "mainnet")
    monkeypatch.setenv("API_SECRET_KEY", "x" * 64)
    monkeypatch.setenv("BOOTSTRAP_API_KEY", "ck_live_" + "x" * 32)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x/y")
    monkeypatch.setenv("LND_MOCK", "false")
    reset_settings_cache()
    errs = Settings().validate_for_runtime()
    assert not any("LND_MOCK" in e for e in errs), errs
    reset_settings_cache()
