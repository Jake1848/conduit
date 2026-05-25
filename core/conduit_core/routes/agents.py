import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_scope
from ..db import get_session
from ..db.models import Agent, Policy
from ..errors import AgentNotFound, InsufficientBalance, InvalidInput
from ..schemas import (
    AgentCreate,
    AgentListOut,
    AgentOut,
    BalanceOut,
    LedgerAdjustIn,
    LedgerAdjustOut,
)
from ..services import ledger
from ..services.ids import agent_id as new_agent_id
from ..services.ids import policy_id as new_policy_id

router = APIRouter(prefix="/v1/agents", tags=["agents"])


async def _locked_agent(session: AsyncSession, agent_id: str) -> Agent:
    """Fetch the agent with a row lock (no-op on SQLite, FOR UPDATE on Postgres)."""
    result = await session.execute(
        select(Agent).where(Agent.id == agent_id).with_for_update()
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise AgentNotFound(f"No agent with id {agent_id}")
    return agent


@router.post("", response_model=AgentOut, status_code=201)
async def create_agent(
    body: AgentCreate,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("admin")),
) -> AgentOut:
    existing = await session.execute(select(Agent).where(Agent.name == body.name))
    if existing.scalar_one_or_none():
        raise InvalidInput(f"Agent with name {body.name!r} already exists")

    agent = Agent(
        id=new_agent_id(),
        name=body.name,
        metadata_json=json.dumps(body.metadata) if body.metadata else None,
        balance_sats=0,
    )
    session.add(agent)

    if body.daily_limit is not None:
        session.add(
            Policy(
                id=new_policy_id(),
                agent_id=agent.id,
                max_per_day=body.daily_limit,
            )
        )

    await session.commit()
    await session.refresh(agent)
    return AgentOut.model_validate(agent)


@router.get("", response_model=AgentListOut)
async def list_agents(
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("read")),
) -> AgentListOut:
    rows = (await session.execute(select(Agent).order_by(Agent.created_at.desc()))).scalars().all()
    return AgentListOut(data=[AgentOut.model_validate(r) for r in rows])


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("read")),
) -> AgentOut:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise AgentNotFound(f"No agent with id {agent_id}")
    return AgentOut.model_validate(agent)


@router.delete("/{agent_id}", status_code=204)
async def deactivate_agent(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("admin")),
) -> None:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise AgentNotFound(f"No agent with id {agent_id}")
    agent.active = False
    await session.commit()


@router.get("/{agent_id}/balance", response_model=BalanceOut)
async def get_balance(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("read")),
) -> BalanceOut:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise AgentNotFound(f"No agent with id {agent_id}")
    # Per-agent virtual balance (see ledger.py). The node balance is reported
    # separately at /v1/status and is the upper bound on the aggregate.
    return BalanceOut(
        agent_id=agent_id,
        available_sats=agent.balance_sats or 0,
        pending_sats=0,
        total_sats=agent.balance_sats or 0,
    )


@router.post("/{agent_id}/credit", response_model=LedgerAdjustOut, status_code=201)
async def credit_agent(
    agent_id: str,
    body: LedgerAdjustIn,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("admin")),
) -> LedgerAdjustOut:
    """Operator-initiated deposit. Used to top up an agent's allowance.

    In a fully-automated deployment this is fired by the invoice settlement
    watcher when an inbound Lightning payment arrives addressed to the agent.
    For now it's also the manual top-up endpoint.
    """
    try:
        agent = await _locked_agent(session, agent_id)
        tx = await ledger.credit(
            session,
            agent,
            sats=body.sats,
            reason=body.reason or "operator credit",
            metadata=body.metadata,
            direction="receive",
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return LedgerAdjustOut(
        agent_id=agent.id,
        transaction_id=tx.id,
        delta_sats=body.sats,
        balance_sats=agent.balance_sats,
    )


@router.post("/{agent_id}/debit", response_model=LedgerAdjustOut, status_code=201)
async def debit_agent(
    agent_id: str,
    body: LedgerAdjustIn,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("admin")),
) -> LedgerAdjustOut:
    """Operator-initiated withdrawal — sweep funds back to the operator wallet
    without going through the Lightning payment path. Useful for treasury moves
    that shouldn't burn an HTLC.
    """
    try:
        agent = await _locked_agent(session, agent_id)
        if (agent.balance_sats or 0) < body.sats:
            raise InsufficientBalance(
                f"Agent balance {agent.balance_sats} sats < requested debit {body.sats} sats",
                agent_id=agent.id,
            )
        tx = await ledger.debit(
            session,
            agent,
            sats=body.sats,
            reason=body.reason or "operator debit",
            metadata=body.metadata,
            direction="send",
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return LedgerAdjustOut(
        agent_id=agent.id,
        transaction_id=tx.id,
        delta_sats=-body.sats,
        balance_sats=agent.balance_sats,
    )
