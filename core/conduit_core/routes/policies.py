import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_scope
from ..db import get_session
from ..db.models import Agent, Policy
from ..errors import AgentNotFound, NotFound
from ..schemas import PolicyIn, PolicyOut
from ..services.ids import policy_id as new_policy_id
from ..services.policy_engine import encode_list

router = APIRouter(prefix="/v1/agents/{agent_id}/policy", tags=["policies"])


def _to_out(p: Policy) -> PolicyOut:
    return PolicyOut(
        id=p.id,
        agent_id=p.agent_id,
        max_per_transaction=p.max_per_transaction,
        max_per_hour=p.max_per_hour,
        max_per_day=p.max_per_day,
        max_per_minute_count=p.max_per_minute_count,
        allowlist=json.loads(p.allowlist) if p.allowlist else [],
        blocklist=json.loads(p.blocklist) if p.blocklist else [],
        require_memo=p.require_memo,
        enabled=p.enabled,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


async def _ensure_agent(session: AsyncSession, agent_id: str) -> Agent:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise AgentNotFound(f"No agent with id {agent_id}")
    return agent


@router.post("", response_model=PolicyOut, status_code=201)
async def attach_policy(
    agent_id: str,
    body: PolicyIn,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("admin")),
) -> PolicyOut:
    await _ensure_agent(session, agent_id)
    existing = (
        await session.execute(select(Policy).where(Policy.agent_id == agent_id))
    ).scalar_one_or_none()
    if existing:
        # idempotent attach == replace
        existing.max_per_transaction = body.max_per_transaction
        existing.max_per_hour = body.max_per_hour
        existing.max_per_day = body.max_per_day
        existing.max_per_minute_count = body.max_per_minute_count or 60
        existing.allowlist = encode_list(body.allowlist)
        existing.blocklist = encode_list(body.blocklist)
        existing.require_memo = body.require_memo
        existing.enabled = body.enabled
        await session.commit()
        await session.refresh(existing)
        return _to_out(existing)

    policy = Policy(
        id=new_policy_id(),
        agent_id=agent_id,
        max_per_transaction=body.max_per_transaction,
        max_per_hour=body.max_per_hour,
        max_per_day=body.max_per_day,
        max_per_minute_count=body.max_per_minute_count or 60,
        allowlist=encode_list(body.allowlist),
        blocklist=encode_list(body.blocklist),
        require_memo=body.require_memo,
        enabled=body.enabled,
    )
    session.add(policy)
    await session.commit()
    await session.refresh(policy)
    return _to_out(policy)


@router.get("", response_model=PolicyOut)
async def get_policy(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("read")),
) -> PolicyOut:
    await _ensure_agent(session, agent_id)
    p = (
        await session.execute(select(Policy).where(Policy.agent_id == agent_id))
    ).scalar_one_or_none()
    if p is None:
        raise NotFound(f"No policy attached to agent {agent_id}")
    return _to_out(p)


@router.put("", response_model=PolicyOut)
async def update_policy(
    agent_id: str,
    body: PolicyIn,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("admin")),
) -> PolicyOut:
    return await attach_policy(agent_id, body, session=session)


@router.delete("", status_code=204)
async def delete_policy(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("admin")),
) -> None:
    await _ensure_agent(session, agent_id)
    p = (
        await session.execute(select(Policy).where(Policy.agent_id == agent_id))
    ).scalar_one_or_none()
    if p is None:
        return
    await session.delete(p)
    await session.commit()
