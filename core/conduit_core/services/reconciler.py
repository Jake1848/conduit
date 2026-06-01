"""Pending-payment reconciler — closes the loop on UNKNOWN-state rows.

When the payment route can't tell whether an LND payment succeeded or
failed (network timeout, 5xx, connection drop), it leaves the Transaction
row in `pending` with the agent's balance still debited, plus a
`needs_reconciliation` marker on `failure_reason`. Without follow-up,
those rows leak agent budget forever.

This service runs on startup and then every `sweep_interval` seconds. For
each pending outbound row older than `min_age_seconds` and with a known
`payment_hash`, we ask LND what actually happened:

  SUCCEEDED  → mark settled, refund unused fee budget, fire payment.settled
  FAILED     → mark failed, refund the full debit, fire payment.failed
  IN_FLIGHT  → leave alone; the next sweep will check again
  UNKNOWN    → LND has no record. Could be a row from before we started
               storing payment_hash, or LND wiped state. Logged and left
               for the operator.

Rows without a payment_hash are skipped — there's nothing to ask LND about.
Operator must resolve those manually.

Concurrency note: the reconciler shares the row-lock pattern used by the
payment route. If a sweep races with a payment that's about to commit a
state transition, one of them will block on the agent row's lock and serialize.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Agent, Transaction
from .lnd import LNDClient, PaymentLookup
from .webhook_sender import fire as fire_webhook

log = structlog.get_logger(__name__)

SessionFactory = Callable[[], AsyncSession]

DEFAULT_SWEEP_INTERVAL_SECONDS = 60.0
# Wait at least this long before reconciling — LND's own timeout_seconds is
# 60s, so a 90s buffer means any payment we look at has had time to reach a
# terminal state under normal conditions.
DEFAULT_MIN_AGE_SECONDS = 90.0


class PaymentReconciler:
    def __init__(
        self,
        lnd: LNDClient,
        session_factory: SessionFactory,
        *,
        sweep_interval: float = DEFAULT_SWEEP_INTERVAL_SECONDS,
        min_age_seconds: float = DEFAULT_MIN_AGE_SECONDS,
    ) -> None:
        self._lnd = lnd
        self._session_factory = session_factory
        self._sweep_interval = sweep_interval
        self._min_age = min_age_seconds
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="conduit-payment-reconciler")
        log.info(
            "payment_reconciler_started",
            sweep_interval=self._sweep_interval,
            min_age_seconds=self._min_age,
        )

    async def stop(self) -> None:
        self._stopping = True
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception) as e:  # noqa: BLE001
            if not isinstance(e, asyncio.CancelledError):
                log.warning("payment_reconciler_stop_error", error=str(e))
        finally:
            self._task = None
            log.info("payment_reconciler_stopped")

    async def _run(self) -> None:
        # Initial sweep ASAP — picks up anything stranded by the previous
        # process exit.
        try:
            await self.sweep()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("reconciler_initial_sweep_failed", err=str(e))

        while not self._stopping:
            try:
                await asyncio.sleep(self._sweep_interval)
            except asyncio.CancelledError:
                raise
            if self._stopping:
                break
            try:
                await self.sweep()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.exception("reconciler_sweep_failed", err=str(e))

    async def sweep(self) -> int:
        """Reconcile every stale-pending send. Returns count of state changes."""
        cutoff = datetime.now(UTC) - timedelta(seconds=self._min_age)
        tx_ids: list[str] = []
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(Transaction.id).where(
                        Transaction.direction == "send",
                        Transaction.status == "pending",
                        Transaction.created_at < cutoff,
                    )
                )
            ).all()
            tx_ids = [r[0] for r in rows]

        changed = 0
        for tx_id in tx_ids:
            try:
                if await self.reconcile_one(tx_id):
                    changed += 1
            except Exception as e:  # noqa: BLE001
                log.exception("reconcile_tx_error", tx_id=tx_id, err=str(e))
        if changed > 0 or tx_ids:
            log.info(
                "reconciler_sweep_complete",
                scanned=len(tx_ids),
                state_changes=changed,
            )
        return changed

    async def reconcile_one(self, tx_id: str) -> bool:
        """Look up a single transaction at LND and apply state changes.

        Public so tests (and operators) can drive a single reconciliation
        without waiting for the next sweep. Returns True if anything changed.
        """
        async with self._session_factory() as session:
            tx = await session.get(Transaction, tx_id)
            if tx is None:
                return False
            if tx.status != "pending" or tx.direction != "send":
                return False
            if not tx.payment_hash:
                log.warning(
                    "reconcile_skip_no_payment_hash",
                    tx_id=tx.id,
                    note="Row predates payment_hash-on-pending; resolve manually.",
                )
                return False

            try:
                lookup = await self._lnd.lookup_payment(tx.payment_hash)
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "lookup_payment_failed",
                    tx_id=tx.id,
                    payment_hash=tx.payment_hash,
                    err=str(e),
                )
                return False

            if lookup.status == "SUCCEEDED":
                return await self._mark_settled(session, tx, lookup)
            if lookup.status == "FAILED":
                return await self._mark_failed(session, tx, lookup)
            # IN_FLIGHT / UNKNOWN — leave for next sweep.
            log.info(
                "reconcile_inflight_or_unknown",
                tx_id=tx.id,
                payment_hash=tx.payment_hash,
                lnd_status=lookup.status,
            )
            return False

    async def _mark_settled(
        self, session: AsyncSession, tx: Transaction, lookup: PaymentLookup
    ) -> bool:
        agent = (
            await session.execute(
                select(Agent).where(Agent.id == tx.agent_id).with_for_update()
            )
        ).scalar_one()
        # Re-read the tx UNDER the agent lock: the payment route's Phase 3 may have
        # terminalized this row while we were looking it up (the 90s eligibility
        # window overlaps an in-flight route call). If it's no longer pending, the
        # route already applied the balance change — bail to avoid double-mutating.
        await session.refresh(tx)
        if tx.status != "pending":
            log.info("reconcile_skip_not_pending", tx_id=tx.id, status=tx.status)
            return False
        actual_fee = max(0, int(lookup.fee_sats))
        # tx.fee_sats currently holds the BUDGET; the actual fee may be lower.
        fee_refund = max(0, tx.fee_sats - actual_fee)
        if fee_refund > 0:
            agent.balance_sats = (agent.balance_sats or 0) + fee_refund

        tx.status = "settled"
        tx.fee_sats = actual_fee
        tx.payment_preimage = lookup.payment_preimage
        tx.settled_at = datetime.now(UTC)
        # Clear the reconciliation marker.
        tx.failure_reason = None
        await session.commit()

        fire_webhook(
            "payment.settled",
            {
                "transaction_id": tx.id,
                "agent_id": tx.agent_id,
                "amount_sats": tx.amount_sats,
                "fee_sats": actual_fee,
                "hash": tx.payment_hash,
                "reconciled": True,
            },
        )
        log.info(
            "reconciled_settled",
            tx_id=tx.id,
            agent_id=tx.agent_id,
            fee=actual_fee,
            refunded=fee_refund,
        )
        return True

    async def _mark_failed(
        self, session: AsyncSession, tx: Transaction, lookup: PaymentLookup
    ) -> bool:
        agent = (
            await session.execute(
                select(Agent).where(Agent.id == tx.agent_id).with_for_update()
            )
        ).scalar_one()
        # Re-read under the agent lock — bail if the route already terminalized it
        # (see _mark_settled), so we never refund a payment twice.
        await session.refresh(tx)
        if tx.status != "pending":
            log.info("reconcile_skip_not_pending", tx_id=tx.id, status=tx.status)
            return False
        # tx.fee_sats currently holds the BUDGET; refund the full debit
        # (amount + budget).
        debit_total = tx.amount_sats + tx.fee_sats
        agent.balance_sats = (agent.balance_sats or 0) + debit_total

        reason = lookup.failure_reason or "unknown"
        tx.status = "failed"
        tx.failure_reason = f"reconciled_failed: {reason}"
        await session.commit()

        fire_webhook(
            "payment.failed",
            {
                "transaction_id": tx.id,
                "agent_id": tx.agent_id,
                "amount_sats": tx.amount_sats,
                "reason": tx.failure_reason,
                "reconciled": True,
            },
        )
        log.info(
            "reconciled_failed",
            tx_id=tx.id,
            agent_id=tx.agent_id,
            refunded=debit_total,
        )
        return True
