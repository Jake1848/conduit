"""Read-only API for the inspectable payment Decision Record.

Every payment attempt — settled, failed, AND policy/balance/destination-rejected —
is queryable here with the margin to each threshold, the applied-policy snapshot,
and who initiated it. READ scope (no secret is ever returned). Mirrors the
transactions list/get convention (limit + has_more, no offset; literal routes
declared before the {id} catch-all).
"""

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_scope
from ..db import get_session
from ..db.models import Agent, PaymentDecision
from ..errors import AgentNotFound, NotFound
from ..schemas import DecisionListOut, DecisionOut, ThresholdOut

router = APIRouter(tags=["decisions"])

_OUTCOME_RE = "^(settled|failed|rejected)$"


def _to_out(d: PaymentDecision) -> DecisionOut:
    # Defensive: stored JSON is always well-formed (only decision_record.py writes
    # it), but a read endpoint must never 500 on a malformed row — fall back to an
    # empty margin list / null snapshot rather than raise, covering both the
    # json.loads AND the subsequent coercion to ThresholdOut/dict.
    try:
        raw = json.loads(d.thresholds_json) if d.thresholds_json else []
        thresholds = [ThresholdOut(**t) for t in raw] if isinstance(raw, list) else []
    except (json.JSONDecodeError, TypeError, ValueError):
        thresholds = []
    try:
        snap = json.loads(d.policy_snapshot_json) if d.policy_snapshot_json else None
        policy_snapshot = snap if isinstance(snap, dict) else None
    except (json.JSONDecodeError, TypeError, ValueError):
        policy_snapshot = None
    return DecisionOut(
        id=d.id,
        agent_id=d.agent_id,
        outcome=d.outcome,
        reason_code=d.reason_code,
        requested_sats=d.requested_sats,
        destination=d.destination,
        destination_kind=d.destination_kind,
        allowlist_status=d.allowlist_status,
        api_key_id=d.api_key_id,
        caller_tag=d.caller_tag,
        balance_at_decision_sats=d.balance_at_decision_sats,
        thresholds=thresholds,
        binding_rule=d.binding_rule,
        min_margin_pct=d.min_margin_pct,
        policy_snapshot=policy_snapshot,
        policy_hash=d.policy_hash,
        tx_id=d.tx_id,
        created_at=d.created_at,
    )


@router.get("/v1/agents/{agent_id}/decisions", response_model=DecisionListOut)
async def list_for_agent(
    agent_id: str,
    limit: int = Query(50, ge=1, le=500),
    outcome: str | None = Query(None, pattern=_OUTCOME_RE),
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("read")),
) -> DecisionListOut:
    """Decisions for one agent, newest first. Filter by `outcome` to surface only
    rejected attempts (the thing operators most want to inspect)."""
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise AgentNotFound(f"No agent with id {agent_id}")
    q = select(PaymentDecision).where(PaymentDecision.agent_id == agent_id)
    if outcome:
        q = q.where(PaymentDecision.outcome == outcome)
    q = q.order_by(PaymentDecision.created_at.desc()).limit(limit + 1)
    rows = (await session.execute(q)).scalars().all()
    has_more = len(rows) > limit
    return DecisionListOut(data=[_to_out(r) for r in rows[:limit]], has_more=has_more)


@router.get("/v1/decisions/recent", response_model=DecisionListOut)
async def list_recent(
    limit: int = Query(50, ge=1, le=500),
    outcome: str | None = Query(None, pattern=_OUTCOME_RE),
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("read")),
) -> DecisionListOut:
    """Most recent decisions across the whole fleet (one query). Powers the dashboard
    decision feed without polling every agent. Server-side `outcome` filter so a
    rejected attempt is never truncated out of a client-side window. Declared BEFORE
    /{decision_id} so 'recent' isn't captured as an id."""
    q = select(PaymentDecision)
    if outcome:
        q = q.where(PaymentDecision.outcome == outcome)
    q = q.order_by(PaymentDecision.created_at.desc()).limit(limit + 1)
    rows = (await session.execute(q)).scalars().all()
    has_more = len(rows) > limit
    return DecisionListOut(data=[_to_out(r) for r in rows[:limit]], has_more=has_more)


@router.get("/v1/decisions/{decision_id}", response_model=DecisionOut)
async def get_decision(
    decision_id: str,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("read")),
) -> DecisionOut:
    d = await session.get(PaymentDecision, decision_id)
    if d is None:
        raise NotFound(f"No decision with id {decision_id}")
    return _to_out(d)
