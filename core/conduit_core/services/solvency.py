"""Solvency monitor — does the operator's real liquidity back the virtual ledger?

Conduit is custodial at the agent layer: every agent's `balance_sats` is a claim
on the operator's single LND node. The sum of those claims (plus the sats locked
up in not-yet-terminal outbound payments) is the operator's LIABILITY. The node's
actual spendable liquidity — outbound channel balance plus confirmed on-chain — is
the ASSET backing it. If liabilities ever exceed assets the operator is technically
insolvent: some agent's balance could not be paid out.

This service mirrors the IdempotencyPruner lifecycle (start/stop + a task loop,
plus an initial pass on boot). On every cycle it:

  liabilities = Σ Agent.balance_sats   (pending sends are already debited from this)
  assets      = LND channel_local_sats + confirmed on-chain
  ratio       = assets / liabilities      (∞ when there are no liabilities)
  solvent     = assets >= liabilities
  (pending_outbound is reported for observability but NOT added to liabilities)

It logs a structured `solvency_snapshot` event and stashes the latest snapshot on
`app.state.solvency` AND in a module-level cache (`latest_snapshot()`) so the
metrics route, the readiness probe, and the Prometheus exporter can read it
without recomputing.

Enforcement is opt-in. With `solvency_enforce=True`, `enforce_solvent()` raises a
ConduitError when the LAST snapshot showed insolvency — the credit path calls it
to fail closed. Default is observe-and-warn (enforce=False) so turning the monitor
on never breaks a live deployment by surprise.

Safe in every mode: against mock LND the assets are the mock balance, so the
ratio is still meaningful in dev/test.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db.models import Agent, Transaction
from ..errors import ConduitError
from .lnd import LNDClient

log = structlog.get_logger(__name__)

SessionFactory = Callable[[], AsyncSession]


class SolvencyError(ConduitError):
    """Raised on a money-IN path when enforcement is on and the ledger is unbacked."""

    code = "solvency_check_failed"
    http_status = 503


@dataclass(frozen=True)
class SolvencySnapshot:
    """The result of one solvency computation. Immutable; replaced atomically."""

    liabilities_sats: int
    assets_sats: int
    # Virtual claims that have to be backed.
    agent_balance_sats: int
    pending_outbound_sats: int
    # Asset breakdown.
    channel_local_sats: int
    onchain_confirmed_sats: int
    solvent: bool
    # assets / liabilities. None when liabilities == 0 (no claims to back — the
    # ratio is undefined / "infinite"; solvent is True in that case).
    ratio: float | None
    computed_at: datetime
    # Set when the LND balance could not be fetched — the snapshot is stale/partial
    # and `solvent` is reported conservatively (see compute_solvency).
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "liabilities_sats": self.liabilities_sats,
            "assets_sats": self.assets_sats,
            "agent_balance_sats": self.agent_balance_sats,
            "pending_outbound_sats": self.pending_outbound_sats,
            "channel_local_sats": self.channel_local_sats,
            "onchain_confirmed_sats": self.onchain_confirmed_sats,
            "solvent": self.solvent,
            "ratio": self.ratio,
            "computed_at": self.computed_at.isoformat(),
            "error": self.error,
        }


# Module-level cache of the most recent snapshot. Read by the metrics route, the
# readiness probe, the Prometheus exporter and enforce_solvent(). Written only by
# the monitor (single writer); a plain assignment is atomic in CPython so no lock
# is needed for the read side.
_latest: SolvencySnapshot | None = None


def latest_snapshot() -> SolvencySnapshot | None:
    """Most recent snapshot, or None if the monitor hasn't run a pass yet."""
    return _latest


def _store(snapshot: SolvencySnapshot) -> None:
    global _latest
    _latest = snapshot


def reset_cache() -> None:
    """Test helper — clears the module cache between tests."""
    global _latest
    _latest = None


async def compute_solvency(
    session: AsyncSession, lnd: LNDClient
) -> SolvencySnapshot:
    """Compute a solvency snapshot from the DB ledger + the LND balance.

    Pure-ish: reads the DB and LND, returns a snapshot. Does NOT store it (callers
    that want to publish call _store / the monitor does). Never raises on an LND
    failure — instead it records the error on the snapshot and reports `solvent`
    conservatively as False so a blind monitor doesn't read as "all good".
    """
    # ---- liabilities ----
    agent_balance = (
        await session.execute(select(func.coalesce(func.sum(Agent.balance_sats), 0)))
    ).scalar_one()
    agent_balance = int(agent_balance or 0)

    # Pending outbound is tracked for OBSERVABILITY only — it is NOT added to
    # liabilities. The payment path debits the agent UP-FRONT (debit-before-pending
    # in routes/payments.py: balance_sats -= amount+fee+platform_fee, then the
    # pending row is committed), so a pending send's sats have ALREADY left
    # Σ balance_sats. Adding them again would double-count and falsely depress the
    # ratio under load. The single source of truth for what the operator owes
    # agents is Σ balance_sats; an in-flight send is money LEAVING the node, not a
    # depositor claim to keep liquidity for.
    pending_outbound = (
        await session.execute(
            select(
                func.coalesce(
                    func.sum(Transaction.amount_sats + Transaction.fee_sats), 0
                )
            ).where(
                and_(
                    Transaction.direction == "send",
                    Transaction.status == "pending",
                )
            )
        )
    ).scalar_one()
    pending_outbound = int(pending_outbound or 0)

    liabilities = agent_balance

    # ---- assets ----
    channel_local = 0
    onchain_confirmed = 0
    err: str | None = None
    try:
        bal = await lnd.get_balance()
        channel_local = int(bal.channel_local_sats)
        onchain_confirmed = int(bal.confirmed_sats)
    except Exception as e:  # noqa: BLE001 - report, never raise from the monitor
        err = type(e).__name__

    assets = channel_local + onchain_confirmed

    if err is not None:
        # Couldn't read assets: don't pretend we're solvent.
        solvent = False
        ratio: float | None = None
    elif liabilities <= 0:
        # No claims to back — trivially solvent; ratio undefined.
        solvent = True
        ratio = None
    else:
        solvent = assets >= liabilities
        ratio = round(assets / liabilities, 6)

    return SolvencySnapshot(
        liabilities_sats=liabilities,
        assets_sats=assets,
        agent_balance_sats=agent_balance,
        pending_outbound_sats=pending_outbound,
        channel_local_sats=channel_local,
        onchain_confirmed_sats=onchain_confirmed,
        solvent=solvent,
        ratio=ratio,
        computed_at=datetime.now(UTC),
        error=err,
    )


def enforce_solvent() -> None:
    """Fail-closed guard for money-IN paths.

    Call this from the credit/payment path BEFORE mutating the ledger. When
    `solvency_enforce` is on and the latest snapshot shows the ledger is not backed
    by node liquidity, this raises SolvencyError (503). When enforcement is off
    (the default) it is a no-op — the monitor still observes and warns. Also a
    no-op until the monitor has produced its first snapshot.
    """
    if not get_settings().solvency_enforce:
        return
    snap = _latest
    if snap is None:
        return
    if not snap.solvent:
        log.error(
            "solvency_enforced_reject",
            liabilities_sats=snap.liabilities_sats,
            assets_sats=snap.assets_sats,
            ratio=snap.ratio,
        )
        raise SolvencyError(
            "Operator node liquidity does not currently back the agent ledger; "
            "credits are paused. Top up channel/on-chain liquidity and retry."
        )


class SolvencyMonitor:
    def __init__(
        self,
        lnd: LNDClient,
        session_factory: SessionFactory,
        *,
        interval_seconds: int,
        enforce: bool = False,
    ) -> None:
        self._lnd = lnd
        self._session_factory = session_factory
        self._interval = max(10, interval_seconds)
        self._enforce = enforce
        self._task: asyncio.Task | None = None
        self._stopping = False
        # Liveness marker — last time a check cycle completed. Exposed via the
        # Prometheus worker-liveness gauge.
        self._last_run_monotonic: float | None = None

    @property
    def last_run_monotonic(self) -> float | None:
        return self._last_run_monotonic

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="conduit-solvency-monitor")
        log.info(
            "solvency_monitor_started",
            interval_seconds=self._interval,
            enforce=self._enforce,
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
                log.warning("solvency_monitor_stop_error", error=str(e))
        finally:
            self._task = None
            log.info("solvency_monitor_stopped")

    async def _run(self) -> None:
        # Initial pass ASAP so the first /metrics / readiness call after boot has
        # a real snapshot (mirrors the reconciler's boot sweep).
        try:
            await self.check()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("solvency_initial_check_failed", error=str(e))

        while not self._stopping:
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                raise
            if self._stopping:
                break
            try:
                await self.check()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("solvency_check_failed", error=str(e))

    async def check(self) -> SolvencySnapshot:
        """Run one solvency computation, publish + log it. Returns the snapshot.

        Public so tests (and operators) can force a check without waiting for the
        next cycle.
        """
        import time as _time

        async with self._session_factory() as session:
            snapshot = await compute_solvency(session, self._lnd)
        _store(snapshot)
        self._last_run_monotonic = _time.monotonic()

        event = {
            "liabilities_sats": snapshot.liabilities_sats,
            "assets_sats": snapshot.assets_sats,
            "ratio": snapshot.ratio,
            "solvent": snapshot.solvent,
            "agent_balance_sats": snapshot.agent_balance_sats,
            "pending_outbound_sats": snapshot.pending_outbound_sats,
            "enforce": self._enforce,
        }
        if snapshot.error is not None:
            log.warning("solvency_snapshot_lnd_error", error=snapshot.error, **event)
        elif not snapshot.solvent:
            log.warning("solvency_snapshot", **event)
        else:
            log.info("solvency_snapshot", **event)
        return snapshot
