"""Treasury service: durable on-chain withdrawal records + fee-reserve sizing.

The withdrawal record is written/updated on its OWN short-lived sessions (not the
route session), so committing it does not release the route's ledger advisory
lock — the lock must stay held across the irreversible broadcast.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import TreasuryWithdrawal
from .ids import withdrawal_id

# Fee-reserve sizing. The reserve is held back from the withdrawable headroom AND
# required on top of the amount, so the on-chain fee can't push assets below
# liabilities. A flat reserve under-cushions a high-fee send, so we scale it by
# the requested fee rate × a conservative sweep vsize.
FEE_RESERVE_FLOOR_SATS = 1000
_DEFAULT_FEE_RATE = 20  # sat/vB assumed when the caller doesn't pin a rate
_EST_VSIZE = 400  # conservative vbytes for a typical 1-2-input wallet send


def fee_reserve_for(sat_per_vbyte: int | None) -> int:
    rate = sat_per_vbyte or _DEFAULT_FEE_RATE
    return max(FEE_RESERVE_FLOOR_SATS, rate * _EST_VSIZE)


async def find_by_key(
    session: AsyncSession, idempotency_key: str
) -> TreasuryWithdrawal | None:
    """Look up an existing withdrawal by Idempotency-Key (the table is the
    idempotency store). Called under the ledger lock so it is race-free."""
    return (
        await session.execute(
            select(TreasuryWithdrawal).where(
                TreasuryWithdrawal.idempotency_key == idempotency_key
            )
        )
    ).scalar_one_or_none()


async def record_pending(
    amount_sats: int,
    address: str,
    sat_per_vbyte: int | None,
    fee_reserve_sats: int,
    idempotency_key: str | None = None,
) -> str:
    """Durably record a `pending` withdrawal BEFORE the broadcast and return its
    id. Its own committed transaction, so a crash after broadcast still leaves a
    reconcilable record."""
    from ..db import SessionLocal

    wid = withdrawal_id()
    async with SessionLocal() as s:
        s.add(
            TreasuryWithdrawal(
                id=wid,
                amount_sats=amount_sats,
                address=address,
                sat_per_vbyte=sat_per_vbyte,
                fee_reserve_sats=fee_reserve_sats,
                status="pending",
                idempotency_key=idempotency_key,
            )
        )
        await s.commit()
    return wid


async def mark_broadcast(
    wid: str, txid: str, assets_after: int | None, liabilities_after: int | None
) -> bool:
    """Flip the record to `broadcast` (+txid). Best-effort: returns False instead
    of raising if the update fails, because the broadcast already happened and a
    bookkeeping error must NOT propagate as a withdrawal failure."""
    from ..db import SessionLocal

    try:
        async with SessionLocal() as s:
            w = await s.get(TreasuryWithdrawal, wid)
            if w is not None:
                w.status = "broadcast"
                w.txid = txid
                w.assets_sats_after = assets_after
                w.liabilities_sats_after = liabilities_after
                await s.commit()
        return True
    except Exception:  # noqa: BLE001 - never let bookkeeping fail a sent withdrawal
        return False


async def reset_to_pending(wid: str, fee_reserve_sats: int) -> None:
    """Re-arm a previously `failed` withdrawal row for a same-key retry. Reusing
    the existing row (instead of inserting a new one with the same idempotency
    key) avoids a self-collision on the unique key index that would otherwise
    brick the retry with a false 409."""
    from ..db import SessionLocal

    async with SessionLocal() as s:
        w = await s.get(TreasuryWithdrawal, wid)
        if w is not None:
            w.status = "pending"
            w.error = None
            w.txid = None
            w.fee_reserve_sats = fee_reserve_sats
            await s.commit()


async def mark_failed(wid: str, error: str) -> None:
    from ..db import SessionLocal

    async with SessionLocal() as s:
        w = await s.get(TreasuryWithdrawal, wid)
        if w is not None:
            w.status = "failed"
            w.error = error[:500]
            await s.commit()


async def recent_withdrawals(
    session: AsyncSession, limit: int = 20
) -> list[TreasuryWithdrawal]:
    rows = (
        await session.execute(
            select(TreasuryWithdrawal)
            .order_by(TreasuryWithdrawal.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)
