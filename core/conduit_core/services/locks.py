"""Coarse advisory lock guarding solvency-sensitive ledger mutations.

A treasury withdrawal reads Σ agent balances (liabilities) and the node's
on-chain balance, checks the solvency guard, then broadcasts an IRREVERSIBLE
on-chain send. Between the read and the broadcast, a concurrent operator
*credit* (which mints a virtual IOU with no matching asset) could raise
liabilities above the post-withdrawal assets — a TOCTOU solvency breach.

`lock_ledger` takes one transaction-scoped Postgres advisory lock so that
withdrawals serialize against each other AND against credits: liabilities
cannot rise inside a withdrawal's read→send window. The lock is released
automatically when the holding transaction commits or rolls back.

Only `credit` needs to take this lock alongside withdraw. Receives (inbound
Lightning settling) raise a liability AND the matching asset together, so they
are solvency-neutral; debits and outbound sends only lower liabilities. So the
hot payment path is untouched.

On SQLite (tests) there are no advisory locks and writes are already
serialized, so this is a no-op.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings

# One fixed key for the ledger lock namespace. Arbitrary but stable 32-bit int.
LEDGER_LOCK_KEY = 0x436F6E64  # "Cond"


async def lock_ledger(session: AsyncSession) -> None:
    """Acquire the transaction-scoped ledger advisory lock (Postgres only).

    Must be called inside the transaction whose duration should hold the lock
    (for a withdrawal: before the solvency read, held across the on-chain send;
    for a credit: before the balance is raised). No-op on SQLite.
    """
    if get_settings().database_url.startswith("postgresql"):
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:k)"), {"k": LEDGER_LOCK_KEY}
        )
