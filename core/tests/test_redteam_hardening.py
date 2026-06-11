"""Regression tests for the v0.8.3 red-team hardening pass.

Each test corresponds to a finding confirmed by the verify+red-team fan-out:
input-validation 500s that should be clean 422s, webhook SSRF validation at
creation time, /v1/status scope tightening, and /v1/agents pagination.
"""
import pytest
from httpx import AsyncClient

from conduit_core.schemas import MAX_SATS


async def _make_agent(client: AsyncClient, name: str = "rt-agent") -> str:
    r = await client.post("/v1/agents", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _read_key(client: AsyncClient) -> str:
    r = await client.post("/v1/api-keys", json={"scope": "read", "label": "rt"})
    assert r.status_code == 201, r.text
    return r.json()["secret"]


# ---- Input hardening: edge inputs return 422, never 500 ----------------------

@pytest.mark.asyncio
async def test_null_byte_in_name_is_422(client: AsyncClient):
    r = await client.post("/v1/agents", json={"name": "evil\x00name"})
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_null_byte_in_credit_reason_is_422(client: AsyncClient):
    agent_id = await _make_agent(client)
    r = await client.post(
        f"/v1/agents/{agent_id}/credit", json={"sats": 100, "reason": "x\x00y"}
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_null_byte_in_apikey_label_is_422(client: AsyncClient):
    r = await client.post("/v1/api-keys", json={"scope": "read", "label": "a\x00b"})
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_oversized_credit_is_422_not_500(client: AsyncClient):
    agent_id = await _make_agent(client)
    # int64 max, int64 max+1, and an absurd integer all exceed MAX_SATS and must
    # be rejected with a clean 422 (previously overflowed Postgres bigint -> 500).
    for sats in (9223372036854775807, 9223372036854775808, 99999999999999999999999999):
        r = await client.post(f"/v1/agents/{agent_id}/credit", json={"sats": sats})
        assert r.status_code == 422, f"sats={sats}: {r.status_code} {r.text}"


@pytest.mark.asyncio
async def test_credit_at_max_sats_boundary_ok(client: AsyncClient):
    agent_id = await _make_agent(client)
    r = await client.post(f"/v1/agents/{agent_id}/credit", json={"sats": MAX_SATS})
    assert r.status_code == 201, r.text
    r2 = await client.post(f"/v1/agents/{agent_id}/credit", json={"sats": MAX_SATS + 1})
    assert r2.status_code == 422, r2.text


# ---- Webhook SSRF: rejected at creation, not just delivery -------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata, non-https
        "https://169.254.169.254/",                  # cloud metadata, https
        "https://127.0.0.1/hook",                    # loopback
        "https://10.0.0.1/hook",                     # private RFC1918
        "http://example.com/hook",                   # non-https
    ],
)
async def test_webhook_internal_url_rejected_at_create(client: AsyncClient, url: str):
    r = await client.post("/v1/webhooks", json={"url": url, "events": ["payment.settled"]})
    assert r.status_code == 422, f"{url}: {r.status_code} {r.text}"


# ---- /v1/status is operator-only (leaks node liquidity) ----------------------

@pytest.mark.asyncio
async def test_status_forbidden_for_read_key(client: AsyncClient):
    secret = await _read_key(client)
    r = await client.get("/v1/status", headers={"Authorization": f"Bearer {secret}"})
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_status_allowed_for_admin(client: AsyncClient):
    # Admin (bootstrap) key must still reach it — not a scope rejection.
    r = await client.get("/v1/status")
    assert r.status_code != 403 and r.status_code != 401, r.text


# ---- /v1/agents pagination (no unbounded table dump) -------------------------

@pytest.mark.asyncio
async def test_agents_list_respects_limit(client: AsyncClient):
    for i in range(3):
        await _make_agent(client, name=f"page-{i}")
    r = await client.get("/v1/agents?limit=2")
    assert r.status_code == 200, r.text
    assert len(r.json()["data"]) == 2


@pytest.mark.asyncio
async def test_agents_list_rejects_bad_limit(client: AsyncClient):
    assert (await client.get("/v1/agents?limit=0")).status_code == 422
    assert (await client.get("/v1/agents?limit=99999")).status_code == 422


@pytest.mark.asyncio
async def test_agents_list_has_more_is_self_describing(client: AsyncClient):
    for i in range(3):
        await _make_agent(client, name=f"hm-{i}")
    full = await client.get("/v1/agents?limit=2")
    assert full.json()["has_more"] is True  # a full page -> maybe more behind
    rest = await client.get("/v1/agents?limit=50")
    assert rest.json()["has_more"] is False  # short page -> end of fleet


@pytest.mark.asyncio
async def test_webhook_valid_hostname_accepted_at_create(client: AsyncClient):
    # Shallow create check: a valid https HOSTNAME is accepted without a DNS
    # lookup (delivery does the authoritative resolve+pin), so transient DNS
    # can't block registering a legit endpoint.
    r = await client.post(
        "/v1/webhooks",
        json={"url": "https://hooks.example.com/conduit", "events": ["payment.settled"]},
    )
    assert r.status_code == 201, r.text
