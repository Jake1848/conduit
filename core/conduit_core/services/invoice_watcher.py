"""Background task that converts LND invoice settlements into agent credits.

When an outsider pays a Lightning invoice created via POST /v1/invoices, the
matching Transaction row was inserted with status='pending' and direction='receive'
but the agent's balance was NOT touched. This watcher subscribes to LND's invoice
stream, finds the matching pending row by payment_hash, marks it settled, credits
the agent's balance atomically (with the agent row locked), and fires an
`invoice.settled` webhook.

Invoices that LND reports as CANCELED (expiry or explicit cancel) are marked
'failed' and emit `invoice.expired` — no balance change since none was reserved.

Reconnection: on any uncaught exception from the subscribe stream the watcher
waits with exponential backoff (1s → 60s cap) and retries. Per-invoice errors
are logged but do not crash the loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Agent, Transaction
from .lnd import InvoiceUpdate, LNDClient
from .webhook_sender import fire as fire_webhook

log = structlog.get_logger(__name__)

SessionFactory = Callable[[], AsyncSession]


class InvoiceWatcher:
    def __init__(self, lnd: LNDClient, session_factory: SessionFactory) -> None:
        self._lnd = lnd
        self._session_factory = session_factory
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="conduit-invoice-watcher")
        log.info("invoice_watcher_started")

    async def stop(self) -> None:
        self._stopping = True
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception) as e:  # noqa: BLE001
            if not isinstance(e, asyncio.CancelledError):
                log.warning("invoice_watcher_stop_error", error=str(e))
        finally:
            self._task = None
            log.info("invoice_watcher_stopped")

    async def _run(self) -> None:
        backoff = 1.0
        while not self._stopping:
            try:
                async for update in self._lnd.subscribe_invoices():
                    try:
                        await self.process_update(update)
                    except Exception as e:  # noqa: BLE001
                        # An individual invoice that we can't process (DB error,
                        # malformed update, etc.) must NOT take down the stream.
                        log.exception(
                            "invoice_watcher_process_error",
                            payment_hash=update.payment_hash,
                            state=update.state,
                            error=str(e),
                        )
                    backoff = 1.0  # any successful read resets backoff
                # Stream ended cleanly. Reconnect after a brief pause.
                if not self._stopping:
                    log.info("invoice_watcher_stream_closed_reconnecting")
                    await asyncio.sleep(backoff)
                    backoff = min(60.0, backoff * 2)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "invoice_watcher_disconnect", error=str(e), retry_in=backoff
                )
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    raise
                backoff = min(60.0, backoff * 2)

    async def process_update(self, update: InvoiceUpdate) -> None:
        """Apply a single invoice state change. Public so tests can drive it."""
        if not update.payment_hash:
            return

        async with self._session_factory() as session:
            try:
                tx = await self._lookup_pending_invoice(session, update.payment_hash)
                if tx is None:
                    return  # not one of ours, or already processed
                if update.state == "SETTLED":
                    await self._mark_settled(session, tx, update)
                elif update.state == "CANCELED":
                    await self._mark_expired(session, tx)
                else:
                    # OPEN / ACCEPTED — nothing to do.
                    return
            except Exception:
                await session.rollback()
                raise

    async def _lookup_pending_invoice(
        self, session: AsyncSession, payment_hash: str
    ) -> Transaction | None:
        row = await session.execute(
            select(Transaction)
            .where(Transaction.payment_hash == payment_hash)
            .with_for_update()
        )
        tx = row.scalar_one_or_none()
        if tx is None:
            return None
        if tx.direction != "receive":
            return None
        if tx.status != "pending":
            return None
        return tx

    async def _mark_settled(
        self, session: AsyncSession, tx: Transaction, update: InvoiceUpdate
    ) -> None:
        # Lock the agent row, credit balance, mark tx settled — all in one
        # transaction so a concurrent payment can't read a half-applied state.
        agent_row = await session.execute(
            select(Agent).where(Agent.id == tx.agent_id).with_for_update()
        )
        agent = agent_row.scalar_one_or_none()
        if agent is None:
            log.error(
                "invoice_settled_no_agent",
                tx_id=tx.id,
                agent_id=tx.agent_id,
                payment_hash=update.payment_hash,
            )
            return

        # Credit the actually-received amount (may exceed the invoice value
        # for AMP payments). Fall back to invoice amount if LND didn't report one.
        credited = update.amount_sats or tx.amount_sats
        agent.balance_sats = (agent.balance_sats or 0) + credited
        tx.status = "settled"
        tx.amount_sats = credited
        tx.settled_at = update.settled_at or datetime.now(UTC)
        await session.commit()

        fire_webhook(
            "invoice.settled",
            {
                "transaction_id": tx.id,
                "agent_id": tx.agent_id,
                "amount_sats": credited,
                "payment_hash": update.payment_hash,
            },
        )
        log.info(
            "invoice_settled",
            tx_id=tx.id,
            agent_id=tx.agent_id,
            sats=credited,
            payment_hash=update.payment_hash,
        )

    async def _mark_expired(self, session: AsyncSession, tx: Transaction) -> None:
        tx.status = "failed"
        tx.failure_reason = "invoice expired or canceled"
        await session.commit()
        fire_webhook(
            "invoice.expired",
            {
                "transaction_id": tx.id,
                "agent_id": tx.agent_id,
                "payment_hash": tx.payment_hash,
            },
        )
        log.info("invoice_expired", tx_id=tx.id, agent_id=tx.agent_id)
