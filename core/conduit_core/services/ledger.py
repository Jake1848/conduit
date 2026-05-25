"""Per-agent ledger helpers.

The agent balance is maintained atomically inside the same DB transaction
that records the Transaction row. The row-level lock on `agents.id` makes
concurrent debit decisions safe on Postgres; on SQLite, BEGIN IMMEDIATE
serializes writes globally so it's also safe (just slower).

Every balance mutation is paired with a Transaction row. We never adjust
agents.balance_sats without an accompanying ledger entry, which makes the
balance reconstructable: balance == sum(credits) - sum(debits) over all
settled transactions.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Agent, Transaction
from .ids import tx_id as new_tx_id


async def credit(
    session: AsyncSession,
    agent: Agent,
    sats: int,
    *,
    reason: str = "",
    metadata: dict | None = None,
    direction: str = "receive",
    destination: str | None = None,
) -> Transaction:
    """Credit the agent balance and record a settled receive transaction.

    Caller is expected to be inside an active transaction with the agent row
    locked (SELECT ... FOR UPDATE).
    """
    if sats <= 0:
        raise ValueError("credit sats must be > 0")
    agent.balance_sats = (agent.balance_sats or 0) + sats
    tx = Transaction(
        id=new_tx_id(),
        agent_id=agent.id,
        direction=direction,
        amount_sats=sats,
        fee_sats=0,
        destination=destination,
        status="settled",
        settled_at=datetime.now(UTC),
        memo=reason or None,
        metadata_json=json.dumps(metadata) if metadata else None,
    )
    session.add(tx)
    return tx


async def debit(
    session: AsyncSession,
    agent: Agent,
    sats: int,
    *,
    reason: str = "",
    metadata: dict | None = None,
    direction: str = "send",
    destination: str | None = None,
) -> Transaction:
    """Debit the agent balance, recording a settled send transaction.

    Used for operator-initiated adjustments (sweeping funds back to the
    operator wallet). For actual Lightning sends, use the route that creates
    a pending Transaction and updates it after LND returns.
    """
    if sats <= 0:
        raise ValueError("debit sats must be > 0")
    if (agent.balance_sats or 0) < sats:
        raise ValueError("insufficient balance")
    agent.balance_sats = (agent.balance_sats or 0) - sats
    tx = Transaction(
        id=new_tx_id(),
        agent_id=agent.id,
        direction=direction,
        amount_sats=sats,
        fee_sats=0,
        destination=destination,
        status="settled",
        settled_at=datetime.now(UTC),
        memo=reason or None,
        metadata_json=json.dumps(metadata) if metadata else None,
    )
    session.add(tx)
    return tx
