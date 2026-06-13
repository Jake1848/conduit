"""Background maintenance — idempotency record retention.

Idempotency reservations/responses accumulate one row per money-moving POST.
They stay useful only for as long as a client might retry (minutes, not days),
so this service prunes rows older than the retention window on a slow loop,
keeping the table — and the index that backs the concurrency lock — small.

Mirrors the PaymentReconciler lifecycle (start/stop + an initial pass on boot)
so wiring it into the app lifespan is uniform. Safe to run in every mode
(mock or real LND); it only touches the idempotency table.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import IdempotencyRecord

log = structlog.get_logger(__name__)

SessionFactory = Callable[[], AsyncSession]


class IdempotencyPruner:
    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        retention_hours: int,
        interval_seconds: int,
    ) -> None:
        self._session_factory = session_factory
        self._retention = timedelta(hours=max(1, retention_hours))
        self._interval = max(60, interval_seconds)
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="conduit-idempotency-pruner")
        log.info(
            "idempotency_pruner_started",
            retention_hours=self._retention.total_seconds() / 3600,
            interval_seconds=self._interval,
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
                log.warning("idempotency_pruner_stop_error", error=str(e))
        finally:
            self._task = None
            log.info("idempotency_pruner_stopped")

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                raise
            if self._stopping:
                break
            try:
                await self.prune()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("idempotency_prune_failed", error=str(e))

    async def prune(self) -> int:
        """Delete idempotency rows past the retention window. Returns row count."""
        cutoff = datetime.now(UTC) - self._retention
        async with self._session_factory() as session:
            result = await session.execute(
                # Only prune FINALIZED rows — NEVER a still-_PENDING (response_status
                # == 0) reservation. Pruning a stranded pending row (from a mid-
                # request crash) would let a much-later same-key retry re-execute a
                # payment that may have already settled — a delayed double-spend. (L4)
                delete(IdempotencyRecord).where(
                    IdempotencyRecord.created_at < cutoff,
                    IdempotencyRecord.response_status != 0,
                )
            )
            await session.commit()
        deleted = result.rowcount or 0
        if deleted:
            log.info("idempotency_pruned", deleted=deleted, cutoff=cutoff.isoformat())
        return deleted
