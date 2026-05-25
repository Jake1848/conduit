from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_scope
from ..db import get_session
from ..db.models import Agent, Transaction
from ..errors import AgentNotFound, NotFound
from ..schemas import TransactionListOut, TransactionOut

router = APIRouter(tags=["transactions"])


def _to_out(t: Transaction) -> TransactionOut:
    return TransactionOut(
        id=t.id,
        agent_id=t.agent_id,
        direction=t.direction,  # type: ignore[arg-type]
        amount_sats=t.amount_sats,
        fee_sats=t.fee_sats,
        destination=t.destination,
        payment_hash=t.payment_hash,
        status=t.status,  # type: ignore[arg-type]
        memo=t.memo,
        settled_at=t.settled_at,
        latency_ms=t.latency_ms,
        created_at=t.created_at,
    )


@router.get("/v1/agents/{agent_id}/transactions", response_model=TransactionListOut)
async def list_for_agent(
    agent_id: str,
    limit: int = Query(50, ge=1, le=500),
    direction: str | None = Query(None, pattern="^(send|receive)$"),
    status: str | None = Query(None, pattern="^(pending|settled|failed)$"),
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("read")),
) -> TransactionListOut:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise AgentNotFound(f"No agent with id {agent_id}")
    q = select(Transaction).where(Transaction.agent_id == agent_id)
    if direction:
        q = q.where(Transaction.direction == direction)
    if status:
        q = q.where(Transaction.status == status)
    q = q.order_by(Transaction.created_at.desc()).limit(limit + 1)
    rows = (await session.execute(q)).scalars().all()
    has_more = len(rows) > limit
    return TransactionListOut(
        data=[_to_out(r) for r in rows[:limit]],
        has_more=has_more,
    )


@router.get("/v1/transactions/{tx_id}", response_model=TransactionOut)
async def get_transaction(
    tx_id: str,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("read")),
) -> TransactionOut:
    t = await session.get(Transaction, tx_id)
    if t is None:
        raise NotFound(f"No transaction with id {tx_id}")
    return _to_out(t)
