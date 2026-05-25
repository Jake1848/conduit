"""Policy engine — the safety-critical piece. Tests verify fail-closed behavior."""

import pytest

from conduit_core.db.models import Agent, Policy
from conduit_core.services.ids import agent_id as new_agent_id
from conduit_core.services.ids import policy_id as new_policy_id
from conduit_core.services.policy_engine import (
    CODE_AMOUNT_INVALID,
    CODE_BLOCKLISTED,
    CODE_DAILY_EXCEEDED,
    CODE_EVALUATION_ERROR,
    CODE_HOURLY_EXCEEDED,
    CODE_MEMO_REQUIRED,
    CODE_NOT_ALLOWLISTED,
    CODE_OK,
    CODE_PER_TX_EXCEEDED,
    CODE_POLICY_DISABLED,
    CODE_RATE_EXCEEDED,
    PaymentRequest,
    PolicyEngine,
    encode_list,
)


async def _make_agent(session) -> Agent:
    a = Agent(id=new_agent_id(), name=f"a-{new_agent_id()}")
    session.add(a)
    await session.commit()
    return a


def _policy_for(agent_id: str, **kw) -> Policy:
    fields = dict(
        id=new_policy_id(),
        agent_id=agent_id,
        max_per_minute_count=60,
        enabled=True,
        require_memo=False,
    )
    fields.update(kw)
    return Policy(**fields)


@pytest.mark.asyncio
async def test_no_policy_allows_with_rate_only(session):
    a = await _make_agent(session)
    eng = PolicyEngine(session)
    d = await eng.evaluate(None, PaymentRequest(a.id, 100, "anywhere", "memo"))
    assert d.allowed and d.code == CODE_OK


@pytest.mark.asyncio
async def test_zero_amount_rejected(session):
    a = await _make_agent(session)
    eng = PolicyEngine(session)
    d = await eng.evaluate(None, PaymentRequest(a.id, 0, "anywhere", "memo"))
    assert not d.allowed and d.code == CODE_AMOUNT_INVALID


@pytest.mark.asyncio
async def test_disabled_policy_blocks(session):
    a = await _make_agent(session)
    p = _policy_for(a.id, enabled=False)
    session.add(p)
    await session.commit()
    d = await PolicyEngine(session).evaluate(p, PaymentRequest(a.id, 100, "x", "m"))
    assert not d.allowed and d.code == CODE_POLICY_DISABLED


@pytest.mark.asyncio
async def test_per_transaction_limit(session):
    a = await _make_agent(session)
    p = _policy_for(a.id, max_per_transaction=1000)
    session.add(p)
    await session.commit()
    eng = PolicyEngine(session)
    assert (await eng.evaluate(p, PaymentRequest(a.id, 1000, "x", "m"))).allowed
    d = await eng.evaluate(p, PaymentRequest(a.id, 1001, "x", "m"))
    assert not d.allowed and d.code == CODE_PER_TX_EXCEEDED


@pytest.mark.asyncio
async def test_memo_required(session):
    a = await _make_agent(session)
    p = _policy_for(a.id, require_memo=True)
    session.add(p)
    await session.commit()
    d = await PolicyEngine(session).evaluate(p, PaymentRequest(a.id, 100, "x", ""))
    assert not d.allowed and d.code == CODE_MEMO_REQUIRED
    d2 = await PolicyEngine(session).evaluate(p, PaymentRequest(a.id, 100, "x", "ok"))
    assert d2.allowed


@pytest.mark.asyncio
async def test_blocklist(session):
    a = await _make_agent(session)
    p = _policy_for(a.id, blocklist=encode_list(["evil@host.com"]))
    session.add(p)
    await session.commit()
    d = await PolicyEngine(session).evaluate(
        p, PaymentRequest(a.id, 100, "evil@host.com", "m")
    )
    assert not d.allowed and d.code == CODE_BLOCKLISTED


@pytest.mark.asyncio
async def test_allowlist_blocks_others(session):
    a = await _make_agent(session)
    p = _policy_for(a.id, allowlist=encode_list(["allowed@host.com"]))
    session.add(p)
    await session.commit()
    eng = PolicyEngine(session)
    bad = await eng.evaluate(p, PaymentRequest(a.id, 100, "stranger@host.com", "m"))
    assert not bad.allowed and bad.code == CODE_NOT_ALLOWLISTED
    good = await eng.evaluate(p, PaymentRequest(a.id, 100, "allowed@host.com", "m"))
    assert good.allowed


@pytest.mark.asyncio
async def test_daily_limit_with_existing_pending(session):
    """Pending sends count against the daily window — prevents racing past the limit."""
    from datetime import datetime, timezone

    from conduit_core.db.models import Transaction
    from conduit_core.services.ids import tx_id as new_tx_id

    a = await _make_agent(session)
    p = _policy_for(a.id, max_per_day=1000)
    session.add(p)
    session.add(
        Transaction(
            id=new_tx_id(),
            agent_id=a.id,
            direction="send",
            amount_sats=800,
            fee_sats=0,
            status="pending",
            created_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()
    d = await PolicyEngine(session).evaluate(p, PaymentRequest(a.id, 300, "x", "m"))
    assert not d.allowed and d.code == CODE_DAILY_EXCEEDED


@pytest.mark.asyncio
async def test_hourly_limit(session):
    from datetime import datetime, timezone

    from conduit_core.db.models import Transaction
    from conduit_core.services.ids import tx_id as new_tx_id

    a = await _make_agent(session)
    p = _policy_for(a.id, max_per_hour=500)
    session.add(p)
    session.add(
        Transaction(
            id=new_tx_id(),
            agent_id=a.id,
            direction="send",
            amount_sats=400,
            fee_sats=0,
            status="settled",
            created_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()
    d = await PolicyEngine(session).evaluate(p, PaymentRequest(a.id, 200, "x", "m"))
    assert not d.allowed and d.code == CODE_HOURLY_EXCEEDED


@pytest.mark.asyncio
async def test_rate_limit_per_minute(session):
    from datetime import datetime, timezone

    from conduit_core.db.models import Transaction
    from conduit_core.services.ids import tx_id as new_tx_id

    a = await _make_agent(session)
    p = _policy_for(a.id, max_per_minute_count=2)
    session.add(p)
    for _ in range(2):
        session.add(
            Transaction(
                id=new_tx_id(),
                agent_id=a.id,
                direction="send",
                amount_sats=10,
                status="settled",
                created_at=datetime.now(timezone.utc),
            )
        )
    await session.commit()
    d = await PolicyEngine(session).evaluate(p, PaymentRequest(a.id, 10, "x", "m"))
    assert not d.allowed and d.code == CODE_RATE_EXCEEDED


@pytest.mark.asyncio
async def test_fail_closed_on_internal_error(session, monkeypatch):
    a = await _make_agent(session)
    p = _policy_for(a.id, max_per_day=1000)
    session.add(p)
    await session.commit()

    async def boom(*a, **kw):
        raise RuntimeError("simulated DB outage")

    monkeypatch.setattr("conduit_core.services.policy_engine._window_sum", boom)
    d = await PolicyEngine(session).evaluate(p, PaymentRequest(a.id, 1, "x", "m"))
    assert not d.allowed and d.code == CODE_EVALUATION_ERROR
