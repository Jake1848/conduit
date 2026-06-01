"""Fleet metrics for the operator dashboard — fleet aggregates + a 24h hourly
series + most-active agents, computed server-side so the dashboard needs one call
instead of fanning out across every agent."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_scope
from ..config import get_settings
from ..db import get_session
from ..db.models import Agent, Transaction
from ..schemas import HourBucket, MetricsOut, TopAgentOut

router = APIRouter(prefix="/v1", tags=["metrics"])


@router.get("/metrics", response_model=MetricsOut)
async def metrics(
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("read")),
) -> MetricsOut:
    now = datetime.now(UTC)
    hour0 = now.replace(minute=0, second=0, microsecond=0)
    cutoff_24h = hour0 - timedelta(hours=23)
    cutoff_1m = now - timedelta(seconds=60)
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    is_pg = get_settings().database_url.startswith("postgresql")

    # ---- fleet scalars ----
    treasury = (
        await session.execute(select(func.coalesce(func.sum(Agent.balance_sats), 0)))
    ).scalar_one()
    active = (
        await session.execute(select(func.count()).select_from(Agent).where(Agent.active.is_(True)))
    ).scalar_one()
    total = (await session.execute(select(func.count()).select_from(Agent))).scalar_one()
    tx_per_min = (
        await session.execute(
            select(func.count()).select_from(Transaction).where(Transaction.created_at >= cutoff_1m)
        )
    ).scalar_one()

    # ---- settlement latency (recent settled sends) ----
    lat_rows = (
        await session.execute(
            select(Transaction.latency_ms)
            .where(Transaction.status == "settled", Transaction.latency_ms.is_not(None))
            .order_by(Transaction.created_at.desc())
            .limit(500)
        )
    ).scalars().all()
    lats = sorted(int(x) for x in lat_rows)
    avg_ms = round(sum(lats) / len(lats)) if lats else None
    p99_ms = lats[min(len(lats) - 1, int(len(lats) * 0.99))] if lats else None

    # ---- 24h hourly buckets (count + volume) ----
    raw: dict[datetime, tuple[int, int]] = {}
    if is_pg:
        bucket = func.date_trunc("hour", Transaction.created_at)
        grp = (
            await session.execute(
                select(
                    bucket.label("h"),
                    func.count(),
                    func.coalesce(func.sum(Transaction.amount_sats), 0),
                )
                .where(Transaction.created_at >= cutoff_24h)
                .group_by(bucket)
            )
        ).all()
        for h, c, v in grp:
            key = h.replace(minute=0, second=0, microsecond=0)
            if key.tzinfo is None:
                key = key.replace(tzinfo=UTC)
            raw[key] = (int(c), int(v))
    else:
        rows = (
            await session.execute(
                select(Transaction.created_at, Transaction.amount_sats).where(
                    Transaction.created_at >= cutoff_24h
                )
            )
        ).all()
        for ts, amt in rows:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            key = ts.replace(minute=0, second=0, microsecond=0)
            c, v = raw.get(key, (0, 0))
            raw[key] = (c + 1, v + int(amt or 0))
    hourly: list[HourBucket] = []
    for i in range(24):
        b = hour0 - timedelta(hours=23 - i)
        c, v = raw.get(b, (0, 0))
        hourly.append(HourBucket(hour=b, count=c, volume_sats=v))

    # ---- top agents by transactions today ----
    top_grp = (
        await session.execute(
            select(Transaction.agent_id, func.count().label("c"))
            .where(Transaction.created_at >= start_today)
            .group_by(Transaction.agent_id)
            .order_by(func.count().desc())
            .limit(20)
        )
    ).all()
    top_ids = [aid for aid, _ in top_grp]
    agents_map: dict[str, Agent] = {}
    if top_ids:
        arows = (await session.execute(select(Agent).where(Agent.id.in_(top_ids)))).scalars().all()
        agents_map = {a.id: a for a in arows}
    top_agents = [
        TopAgentOut(
            agent_id=aid,
            name=(a.name if (a := agents_map.get(aid)) else aid),
            tx_today=int(c),
            balance_sats=(agents_map[aid].balance_sats if aid in agents_map else 0),
            active=(agents_map[aid].active if aid in agents_map else True),
        )
        for aid, c in top_grp
    ]

    return MetricsOut(
        treasury_sats=int(treasury),
        active_agents=int(active),
        total_agents=int(total),
        tx_per_min=int(tx_per_min),
        avg_settlement_ms=avg_ms,
        p99_settlement_ms=p99_ms,
        hourly=hourly,
        top_agents=top_agents,
    )
