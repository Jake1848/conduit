"""Inspectable payment Decision Record — capture correctness (Phase 5).

Asserts the decision record is correct for the full matrix — settled, policy-
rejected, near-miss-that-PASSED, insufficient-balance, split-to-evade, malformed
destination, and a failed/refunded payment — AND that no money moves on a
rejection. Also pins the two hard guarantees (no secrets stored; the audit write
never breaks the money path) and the policy-admin separation (Phase 4).

The GET /v1/decisions API is exercised separately; here we read the rows directly
to prove the CAPTURE is correct end-to-end through the live money path.
"""

import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from conduit_core.db.database import SessionLocal
from conduit_core.db.models import PaymentDecision, Transaction

from .conftest import credit_agent

PUBKEY = "02" + "be" * 32  # a 66-char hex pubkey for keysend (mock LND settles it)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


async def _make_agent(client: AsyncClient, name: str, **policy) -> str:
    agent_id = (await client.post("/v1/agents", json={"name": name})).json()["id"]
    if policy:
        r = await client.post(f"/v1/agents/{agent_id}/policy", json=policy)
        assert r.status_code == 201, r.text
    return agent_id


async def _pay(client: AsyncClient, agent_id: str, sats: int, **extra):
    return await client.post(
        "/v1/payments/send",
        json={"agent_id": agent_id, "dest_pubkey": PUBKEY, "sats": sats},
        **extra,
    )


async def _decisions(agent_id: str) -> list[PaymentDecision]:
    async with SessionLocal() as s:
        return list(
            (
                await s.execute(
                    select(PaymentDecision)
                    .where(PaymentDecision.agent_id == agent_id)
                    .order_by(PaymentDecision.created_at, PaymentDecision.id)
                )
            )
            .scalars()
            .all()
        )


async def _balance(client: AsyncClient, agent_id: str) -> int:
    return (await client.get(f"/v1/agents/{agent_id}")).json()["balance_sats"]


async def _tx_count(agent_id: str) -> int:
    """Count outbound (send) transactions only — a `credit` writes a receive row."""
    async with SessionLocal() as s:
        return len(
            (
                await s.execute(
                    select(Transaction).where(
                        Transaction.agent_id == agent_id,
                        Transaction.direction == "send",
                    )
                )
            )
            .scalars()
            .all()
        )


def _threshold(d: PaymentDecision, rule: str) -> dict | None:
    for t in json.loads(d.thresholds_json or "[]"):
        if t["rule"] == rule:
            return t
    return None


# --------------------------------------------------------------------------- #
# settled — record carries the margin even though it passed (the near-miss)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_settled_near_miss_records_margin(client: AsyncClient):
    # daily cap 1000; pay 950 → ALLOWED with only 50 sats (5%) of headroom.
    agent_id = await _make_agent(client, "near-miss", max_per_day=1000)
    await credit_agent(client, agent_id, 100_000)
    before = await _balance(client, agent_id)

    r = await _pay(client, agent_id, 950)
    assert r.status_code == 201, r.text

    decs = await _decisions(agent_id)
    assert len(decs) == 1
    d = decs[0]
    assert d.outcome == "settled"
    assert d.reason_code is None
    assert d.requested_sats == 950
    assert d.tx_id is not None  # linked to the settled transaction

    daily = _threshold(d, "daily")
    assert daily is not None, "margin must be recorded even on a PASS"
    assert daily["limit"] == 1000
    assert daily["attempted"] == 950
    assert daily["margin_abs"] == 50
    assert daily["violated"] is False
    # the headline: a passed payment that squeaked under by a hair is visible
    assert d.binding_rule == "daily"
    assert d.min_margin_pct == pytest.approx(5.0, abs=0.01)

    # money DID move on a settle
    assert await _balance(client, agent_id) < before
    # policy is reconstructable: snapshot + hash captured
    assert d.policy_hash and len(d.policy_hash) == 64
    assert json.loads(d.policy_snapshot_json)["max_per_day"] == 1000


# --------------------------------------------------------------------------- #
# policy-rejected — recorded, NO money moved (the core gap, now closed)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_policy_rejected_recorded_no_money_moved(client: AsyncClient):
    agent_id = await _make_agent(client, "blocked", max_per_transaction=500)
    await credit_agent(client, agent_id, 100_000)
    before = await _balance(client, agent_id)

    r = await _pay(client, agent_id, 1000)  # over the per-tx cap
    assert r.status_code == 403, r.text

    decs = await _decisions(agent_id)
    assert len(decs) == 1
    d = decs[0]
    assert d.outcome == "rejected"
    assert d.reason_code == "PER_TRANSACTION_LIMIT_EXCEEDED"
    assert d.tx_id is None  # no transaction was ever created

    per_tx = _threshold(d, "per_transaction")
    assert per_tx is not None
    assert per_tx["limit"] == 500
    assert per_tx["attempted"] == 1000
    assert per_tx["margin_abs"] == -500  # 500 over
    assert per_tx["violated"] is True
    assert d.min_margin_pct < 0  # over the limit

    # the whole point: NO money moved, and there is now a durable trace
    assert await _balance(client, agent_id) == before
    assert await _tx_count(agent_id) == 0


# --------------------------------------------------------------------------- #
# insufficient balance — recorded with the balance margin, no money moved
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_insufficient_balance_recorded(client: AsyncClient):
    agent_id = await _make_agent(client, "broke", max_per_transaction=1_000_000)
    await credit_agent(client, agent_id, 100)  # nowhere near enough
    before = await _balance(client, agent_id)

    r = await _pay(client, agent_id, 5_000)
    assert r.status_code == 402, r.text

    decs = await _decisions(agent_id)
    assert len(decs) == 1
    d = decs[0]
    assert d.outcome == "rejected"
    assert d.reason_code == "INSUFFICIENT_BALANCE"
    bal = _threshold(d, "balance")
    assert bal is not None and bal["violated"] is True
    assert bal["limit"] == 100  # available balance at decision time

    assert await _balance(client, agent_id) == before
    assert await _tx_count(agent_id) == 0


# --------------------------------------------------------------------------- #
# split-to-evade — each attempt recorded with a shrinking margin; the cap catches it
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_split_to_evade_daily_cap_each_recorded(client: AsyncClient):
    agent_id = await _make_agent(client, "splitter", max_per_day=1000)
    await credit_agent(client, agent_id, 100_000)

    assert (await _pay(client, agent_id, 400)).status_code == 201
    assert (await _pay(client, agent_id, 400)).status_code == 201
    assert (await _pay(client, agent_id, 400)).status_code == 403  # 1200 > 1000 daily

    decs = await _decisions(agent_id)
    assert [d.outcome for d in decs] == ["settled", "settled", "rejected"]

    margins = [_threshold(d, "daily")["margin_abs"] for d in decs]
    # headroom shrinks each attempt, and the last one is negative (over the cap)
    assert margins[0] > margins[1] > margins[2]
    assert margins[2] < 0
    assert decs[2].reason_code == "DAILY_LIMIT_EXCEEDED"


# --------------------------------------------------------------------------- #
# malformed destination — rejected at the edge, recorded, no funds stranded
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_malformed_destination_recorded(client: AsyncClient):
    agent_id = await _make_agent(client, "malformed")
    await credit_agent(client, agent_id, 100_000)
    before = await _balance(client, agent_id)

    r = await client.post(
        "/v1/payments/send",
        json={"agent_id": agent_id, "payment_request": "not-a-real-invoice", "sats": 100},
    )
    assert r.status_code >= 400

    decs = await _decisions(agent_id)
    assert len(decs) == 1
    assert decs[0].outcome == "rejected"
    assert decs[0].reason_code == "INVALID_REQUEST"
    assert decs[0].tx_id is None
    assert await _balance(client, agent_id) == before
    assert await _tx_count(agent_id) == 0


# --------------------------------------------------------------------------- #
# failed payment — refunded, recorded as failed with a tx link
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_failed_payment_recorded_and_refunded(client: AsyncClient, monkeypatch):
    from conduit_core.errors import PaymentFailed
    from conduit_core.services.lnd import get_lnd

    async def _boom(*a, **kw):
        raise PaymentFailed("no route to destination")

    monkeypatch.setattr(get_lnd(), "keysend", _boom)

    agent_id = await _make_agent(client, "unroutable", max_per_transaction=1_000_000)
    await credit_agent(client, agent_id, 100_000)
    before = await _balance(client, agent_id)

    r = await _pay(client, agent_id, 500)
    assert r.status_code >= 400

    decs = await _decisions(agent_id)
    assert len(decs) == 1
    d = decs[0]
    assert d.outcome == "failed"
    assert d.reason_code == "PAYMENT_FAILED"
    assert d.tx_id is not None  # a failed transaction row exists
    # the debit was fully refunded on definite failure
    assert await _balance(client, agent_id) == before


# --------------------------------------------------------------------------- #
# hard guarantee — no secrets stored; caller tag is opt-in
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_no_secrets_stored_and_caller_tag_opt_in(client: AsyncClient):
    agent_id = await _make_agent(client, "secrets", max_per_day=100_000)
    await credit_agent(client, agent_id, 100_000)

    # no caller header → caller_tag is null (opt-in)
    assert (await _pay(client, agent_id, 100)).status_code == 201
    # with the opt-in header → short tag captured, never a prompt dump
    assert (
        await _pay(client, agent_id, 100, headers={"X-Conduit-Caller": "research-bot/v2"})
    ).status_code == 201

    decs = await _decisions(agent_id)
    assert decs[0].caller_tag is None
    assert decs[1].caller_tag == "research-bot/v2"

    for d in decs:
        # api_key_id is the key's id, NEVER the secret
        assert d.api_key_id and d.api_key_id.startswith("key_")
        assert not (d.api_key_id or "").startswith("ck_")
        # the model has no column for preimage/secret/seed at all
        cols = {c.name for c in d.__table__.columns}
        assert not (cols & {"preimage", "payment_preimage", "secret", "seed", "key_hash"})
        # and no secret leaked into the JSON blobs
        blob = (d.thresholds_json or "") + (d.policy_snapshot_json or "")
        assert "preimage" not in blob and "secret" not in blob


# --------------------------------------------------------------------------- #
# Phase 4 — policy-admin separation: a write-scope key cannot mutate policy
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_write_scope_key_cannot_mutate_policy(client: AsyncClient):
    agent_id = await _make_agent(client, "scoped")

    # mint a write-scope key with the admin bootstrap key
    created = (
        await client.post("/v1/api-keys", json={"scope": "write", "label": "agent-pay-key"})
    ).json()
    write_secret = created["secret"]
    assert created["scope"] == "write"

    from httpx import ASGITransport

    from conduit_core.main import app

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as wc:
        wc.headers["Authorization"] = f"Bearer {write_secret}"
        # the agent's PAYING key must NOT be able to change its own caps/allowlist
        r = await wc.post(
            f"/v1/agents/{agent_id}/policy", json={"max_per_transaction": 999_999_999}
        )
        assert r.status_code == 403, r.text
        # ...nor delete it
        assert (await wc.delete(f"/v1/agents/{agent_id}/policy")).status_code == 403

    # the admin key still can (sanity)
    assert (
        await client.post(f"/v1/agents/{agent_id}/policy", json={"max_per_transaction": 500})
    ).status_code == 201


# --------------------------------------------------------------------------- #
# Phase 3 — the read API exposes decisions (list, filter, get-by-id, recent)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_decisions_api_list_filter_and_get(client: AsyncClient):
    agent_id = await _make_agent(
        client, "api-agent", max_per_transaction=500, max_per_day=100_000
    )
    await credit_agent(client, agent_id, 100_000)
    assert (await _pay(client, agent_id, 450)).status_code == 201  # settled (under per-tx)
    assert (await _pay(client, agent_id, 1000)).status_code == 403  # rejected (over per-tx)

    # list for agent
    body = (await client.get(f"/v1/agents/{agent_id}/decisions")).json()
    assert body["has_more"] is False
    assert {d["outcome"] for d in body["data"]} == {"settled", "rejected"}

    # filter by outcome=rejected → the margin round-trips through the API
    rejected = (
        await client.get(f"/v1/agents/{agent_id}/decisions", params={"outcome": "rejected"})
    ).json()["data"]
    assert len(rejected) == 1
    dec = rejected[0]
    assert dec["reason_code"] == "PER_TRANSACTION_LIMIT_EXCEEDED"
    per_tx = next(t for t in dec["thresholds"] if t["rule"] == "per_transaction")
    assert per_tx["limit"] == 500 and per_tx["attempted"] == 1000 and per_tx["violated"] is True
    assert dec["min_margin_pct"] < 0
    assert dec["policy_snapshot"]["max_per_transaction"] == 500
    assert dec["api_key_id"].startswith("key_")  # never the secret

    # get one full record by id
    one = (await client.get(f"/v1/decisions/{dec['id']}")).json()
    assert one["id"] == dec["id"] and one["outcome"] == "rejected"

    # fleet-wide recent feed with server-side outcome filter
    recent = (await client.get("/v1/decisions/recent", params={"outcome": "settled"})).json()
    assert all(d["outcome"] == "settled" for d in recent["data"])
    assert any(d["agent_id"] == agent_id for d in recent["data"])

    # 'recent' literal is not captured as an id; unknown id → 404
    assert (await client.get("/v1/decisions/dec_does_not_exist")).status_code == 404


# --------------------------------------------------------------------------- #
# Hard guarantee — an audit-write failure can NEVER break the money path
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_audit_write_failure_does_not_break_payment(client: AsyncClient, monkeypatch):
    """Force the decision-record INSERT to blow up and prove the payment still
    settles correctly (201 + debited balance) and nothing is recorded — the headline
    'audit never breaks the money path' guarantee."""
    import conduit_core.services.decision_record as drmod

    def _boom(*a, **kw):
        raise RuntimeError("decision-record DB is down")

    # Make PaymentDecision(...) raise INSIDE record_decision (its own try/except must
    # swallow it). The money path uses the real Transaction model and is unaffected.
    monkeypatch.setattr(drmod, "PaymentDecision", _boom)

    agent_id = await _make_agent(client, "audit-down", max_per_day=100_000)
    await credit_agent(client, agent_id, 100_000)
    before = await _balance(client, agent_id)

    r = await _pay(client, agent_id, 500)
    assert r.status_code == 201, r.text  # payment STILL succeeds
    assert await _balance(client, agent_id) < before  # and was actually debited
    assert await _tx_count(agent_id) == 1  # the transaction was written

    # the audit write was swallowed → no decision row (the metered, best-effort gap)
    assert await _decisions(agent_id) == []
