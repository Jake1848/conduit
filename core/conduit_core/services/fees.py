"""Platform fee — the Conduit operator's per-payment revenue.

Self-hosted model: the operator runs Conduit against their OWN LND node. On every
successful outbound payment, Conduit debits the agent a small platform fee ON TOP
of the payment amount and the LND routing-fee budget. The payment amount + actual
routing fee leave the operator's node over Lightning; the platform fee never leaves
— it is simply retained in the operator's node as revenue. So "fees collected" is an
accounting view over settled transactions (sum of platform_fee_sats), not a separate
transfer.

This fee is DISTINCT from `fee_sats` (the LND routing-fee budget, which pays Lightning
routing nodes and whose unused remainder is refunded to the agent). Never conflate them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db.models import Transaction
from ..schemas import FeeDayBucket, FeesOut

_FEE_DAY_WINDOW = 30  # days of history returned in fees_by_day


async def aggregate_fees(session: AsyncSession) -> FeesOut:
    """Accounting rollup of settled platform fees (operator revenue).

    Shared by GET /v1/fees and the treasury overview. Fees are only "collected"
    on a SETTLED outbound payment (failures are refunded in full), so every
    aggregate filters on direction == 'send' AND status == 'settled'.
    """
    now = datetime.now(UTC)
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    window_start = start_today - timedelta(days=_FEE_DAY_WINDOW - 1)
    is_pg = get_settings().database_url.startswith("postgresql")

    settled_send = (Transaction.direction == "send", Transaction.status == "settled")
    fee_sum = func.coalesce(func.sum(Transaction.platform_fee_sats), 0)

    total = (await session.execute(select(fee_sum).where(*settled_send))).scalar_one()
    today = (
        await session.execute(
            select(fee_sum).where(*settled_send, Transaction.created_at >= start_today)
        )
    ).scalar_one()

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


def compute_platform_fee(
    amount_sats: int, percent: float, min_sats: int, max_sats: int
) -> int:
    """Platform fee for a payment of `amount_sats`.

    `percent` is a percentage (0.5 == 0.5%). The raw fee is clamped to
    [min_sats, max_sats] so tiny payments still pay the floor and large payments
    aren't punished beyond the cap. `percent <= 0` disables the fee entirely
    (returns 0) — a self-hosting operator may choose to charge nothing.
    """
    if percent <= 0 or amount_sats <= 0:
        return 0
    raw = round(amount_sats * percent / 100.0)
    # Guard against a misconfigured min > max: the cap always wins.
    floor = max(0, min(min_sats, max_sats))
    return max(floor, min(max_sats, raw))
