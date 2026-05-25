import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_scope
from ..db import get_session
from ..db.models import Agent, Policy
from ..errors import AgentNotFound, InvalidInput
from ..schemas import (
    AgentCreate,
    AgentListOut,
    AgentOut,
    BalanceOut,
)
from ..services.ids import agent_id as new_agent_id
from ..services.ids import policy_id as new_policy_id
from ..services.lnd import get_lnd

router = APIRouter(prefix="/v1/agents", tags=["agents"])


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
    # Per-agent virtual balance = node balance for now (single-wallet design).
    # In a multi-tenant deployment, this becomes an internal ledger sum.
    bal = await get_lnd().get_balance()
    return BalanceOut(
        agent_id=agent_id,
        available_sats=bal.available_sats,
        pending_sats=bal.pending_sats,
        total_sats=bal.total_sats,
    )
