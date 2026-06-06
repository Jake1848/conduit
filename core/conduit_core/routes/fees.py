"""Platform-fee revenue for the self-hosted operator.

Reports the operator's accumulated platform fees — the per-payment revenue charged
on top of each payment (see services/fees.py). Fees are only "collected" on a
SETTLED payment (failed payments are refunded in full), so every aggregate here
filters on status == 'settled'. This is an accounting view over transactions; the
sats themselves are simply retained in the operator's own LND node.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_scope
from ..config import get_settings
from ..db import get_session
from ..db.models import Transaction
from ..schemas import FeeDayBucket, FeesOut

router = APIRouter(prefix="/v1", tags=["fees"])

_FEE_DAY_WINDOW = 30  # days of history returned in fees_by_day


@router.get("/fees", response_model=FeesOut)
async def fees(
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("admin")),
) -> FeesOut:
    now = datetime.now(UTC)
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    window_start = start_today - timedelta(days=_FEE_DAY_WINDOW - 1)
    is_pg = get_settings().database_url.startswith("postgresql")

    settled_send = (Transaction.direction == "send", Transaction.status == "settled")
    fee_sum = func.coalesce(func.sum(Transaction.platform_fee_sats), 0)

    total = (
        await session.execute(select(fee_sum).where(*settled_send))
    ).scalar_one()
    today = (
        await session.execute(
            select(fee_sum).where(*settled_send, Transaction.created_at >= start_today)
        )
    ).scalar_one()

    # ---- fees grouped by UTC day (last _FEE_DAY_WINDOW days) ----
    by_day: dict[str, tuple[int, int]] = {}
    if is_pg:
        bucket = func.date_trunc("day", Transaction.created_at)
        rows = (
            await session.execute(
                select(bucket.label("d"), fee_sum, func.count())
                .where(*settled_send, Transaction.created_at >= window_start)
                .group_by(bucket)
            )
        ).all()
        for d, s, c in rows:
            key = (d.date() if hasattr(d, "date") else d).isoformat()[:10]
            by_day[key] = (int(s), int(c))
    else:
        rows = (
            await session.execute(
                select(Transaction.created_at, Transaction.platform_fee_sats).where(
                    *settled_send, Transaction.created_at >= window_start
                )
            )
        ).all()
        for ts, fee in rows:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            key = ts.date().isoformat()
            s, c = by_day.get(key, (0, 0))
            by_day[key] = (s + int(fee or 0), c + 1)

    fees_by_day = [
        FeeDayBucket(date=k, sats=v[0], tx_count=v[1])
        for k, v in sorted(by_day.items(), reverse=True)
    ]

    return FeesOut(
        total_collected_sats=int(total),
        total_collected_btc=round(int(total) / 1e8, 8),
        today_sats=int(today),
        fees_by_day=fees_by_day,
    )
