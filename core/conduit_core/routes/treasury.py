"""Treasury — owner/admin revenue view + on-chain withdrawal of accrued BTC.

Revenue is an ACCOUNTING figure (Σ settled platform_fee_sats), commingled with
node liquidity — NOT a segregated wallet. A withdrawal moves the operator's
on-chain balance and is gated by a hard SOLVENCY guard: after the send, node
assets (on-chain confirmed + local channel balance) must still cover liabilities
(Σ agent balances).

Concurrency: the withdraw holds a transaction-scoped ledger advisory lock across
the solvency read AND the irreversible broadcast, so neither a concurrent
withdrawal nor a concurrent operator credit can invalidate the guard in the
window (see services/locks.py). The withdrawal is durably recorded `pending`
before the broadcast and `broadcast` (+txid) after, so a crash mid-broadcast
leaves a reconcilable record. Admin scope only; honours Idempotency-Key.

KNOWN LIMITATION (crash recovery): if the process dies between the committed
`pending` record and the broadcast — or mark_broadcast fails after a successful
broadcast — the row stays `pending`, and a same-key retry returns 409 (we can't
safely auto-retry: the broadcast MAY have happened). Recovery is operator-driven:
the durable row holds amount+address+key, so the operator reconciles against LND
and resolves it. An automated reconciler (match `pending` rows to on-chain sends
by amount/address past a TTL) is a planned follow-up.
"""

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_scope
from ..db import get_session
from ..db.models import TreasuryWithdrawal
from ..errors import IdempotencyConflict, InvalidInput, LNDError
from ..schemas import TreasuryOverviewOut, WithdrawalItem, WithdrawIn, WithdrawOut
from ..services import treasury as twd
from ..services.fees import aggregate_fees
from ..services.lnd import LNDClient, get_lnd
from ..services.locks import lock_ledger
from ..services.solvency import compute_solvency

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/v1/treasury", tags=["treasury"])


def _withdrawable(assets: int, liabilities: int, onchain: int, reserve: int) -> int:
    """Max sats withdrawable on-chain now, bounded by BOTH the solvency headroom
    (assets - liabilities) and the on-chain confirmed balance, each minus the fee
    reserve. Never negative."""
    headroom = assets - liabilities - reserve
    onchain_cap = onchain - reserve
    return max(0, min(headroom, onchain_cap))


def _liabilities(snap) -> int:
    """CONSERVATIVE liabilities for withdrawal decisions: Σ agent balances PLUS
    in-flight (pending) outbound sends. A pending send is debited up-front, but a
    concurrent failure/refund (route Phase 3a, the reconciler, the invoice
    watcher) puts those sats back into agent balances — raising liabilities. For
    'how much may leave the node on-chain' we must treat pending sends as
    still-owed, or a concurrent refund could breach solvency inside the
    read→send window (audit H2/M1 — a TOCTOU the advisory lock doesn't cover for
    the background refund paths)."""
    return snap.liabilities_sats + snap.pending_outbound_sats


async def _overview(session: AsyncSession) -> TreasuryOverviewOut:
    lnd = get_lnd()
    fees = await aggregate_fees(session)
    snap = await compute_solvency(session, lnd)
    reserve = twd.fee_reserve_for(None)
    liab = _liabilities(snap)
    rows = await twd.recent_withdrawals(session)
    return TreasuryOverviewOut(
        revenue_total_sats=fees.total_collected_sats,
        revenue_total_btc=fees.total_collected_btc,
        revenue_today_sats=fees.today_sats,
        revenue_by_day=fees.fees_by_day,
        onchain_confirmed_sats=snap.onchain_confirmed_sats,
        channel_local_sats=snap.channel_local_sats,
        assets_sats=snap.assets_sats,
        agent_liabilities_sats=liab,
        solvent=snap.solvent,
        solvency_ratio=snap.ratio,
        withdrawable_sats=_withdrawable(
            snap.assets_sats, liab, snap.onchain_confirmed_sats, reserve
        ),
        fee_reserve_sats=reserve,
        recent_withdrawals=[WithdrawalItem.model_validate(r) for r in rows],
        error=snap.error,
    )


@router.get("/overview", response_model=TreasuryOverviewOut)
async def overview(
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("admin")),
) -> TreasuryOverviewOut:
    return await _overview(session)


async def _remaining(
    session: AsyncSession, lnd: LNDClient
) -> tuple[int | None, int | None, int | None]:
    """Current (assets, liabilities, withdrawable) for the response — best-effort
    fresh read; returns (None, None, None) if LND is unreadable so the client
    shows '—' rather than a misleading 0. Never raises (a post-broadcast read
    failure must not fail a sent withdrawal)."""
    try:
        snap = await compute_solvency(session, lnd)
        if snap.error is None:
            liab = _liabilities(snap)
            return (
                snap.assets_sats,
                liab,
                _withdrawable(
                    snap.assets_sats,
                    liab,
                    snap.onchain_confirmed_sats,
                    twd.fee_reserve_for(None),
                ),
            )
    except Exception:  # noqa: BLE001 - bookkeeping must not fail a sent withdrawal
        log.warning("treasury.remaining.read_failed")
    return (None, None, None)


async def _out_from_record(
    session: AsyncSession, lnd: LNDClient, rec: TreasuryWithdrawal
) -> WithdrawOut:
    """Build the response for an already-recorded (idempotent-replayed) withdrawal."""
    assets, liabilities, withdrawable = await _remaining(session, lnd)
    return WithdrawOut(
        withdrawal_id=rec.id,
        txid=rec.txid or "",
        amount_sats=rec.amount_sats,
        address=rec.address,
        status=rec.status,
        assets_sats=rec.assets_sats_after if rec.assets_sats_after is not None else assets,
        agent_liabilities_sats=(
            rec.liabilities_sats_after if rec.liabilities_sats_after is not None else liabilities
        ),
        withdrawable_sats_remaining=withdrawable,
    )


@router.post("/withdraw", response_model=WithdrawOut, status_code=201)
async def withdraw(
    body: WithdrawIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("admin")),
) -> WithdrawOut:
    lnd = get_lnd()
    idem_key = (request.headers.get("Idempotency-Key") or "").strip() or None

    # Hold the ledger lock across the idempotency check, the solvency read AND the
    # broadcast, so no concurrent credit/withdrawal can race the guard or the
    # idempotency check.
    await lock_ledger(session)

    # Idempotency: the treasury_withdrawals table IS the store (the payment
    # idempotency wrapper caches FAILURES, which is wrong here — a guard failure
    # is self-healing and a post-broadcast bookkeeping error must never cache a
    # sent withdrawal as failed). A prior `broadcast` row dedupes; a `pending`
    # row is genuinely in-flight; a `failed`/absent row is safe to re-attempt
    # because nothing left the wallet.
    if idem_key is not None:
        prior = await twd.find_by_key(session, idem_key)
        if prior is not None:
            # Same key reused with a DIFFERENT withdrawal is a client bug — never
            # silently return the old one. (Body fields are stored on the record.)
            if (
                prior.amount_sats != body.amount_sats
                or prior.address != body.address
                or prior.sat_per_vbyte != body.sat_per_vbyte
            ):
                raise IdempotencyConflict(
                    "This Idempotency-Key was already used for a different "
                    "withdrawal. Use a fresh key."
                )
            if prior.status == "broadcast":
                return await _out_from_record(session, lnd, prior)
            # pending OR unknown → a same-key retry must NEVER re-broadcast.
            # `pending` is genuinely in-flight; `unknown` means send_coins raised
            # and MAY have broadcast (a timeout/drop after the tx was sent). Both
            # are ambiguous-or-in-progress: re-sending would double-spend. The
            # operator reconciles against the chain (amount+address) and uses a
            # fresh Idempotency-Key for a genuinely new withdrawal.
            raise IdempotencyConflict(
                "A withdrawal with this Idempotency-Key is already in progress "
                "or in an unknown state — it may have broadcast on-chain. Check "
                "the Bitcoin-transfers history before retrying; use a fresh key "
                "for a new withdrawal.",
                in_progress=True,
            )

    snap = await compute_solvency(session, lnd)
    if snap.error is not None:
        raise LNDError(f"cannot verify solvency before withdrawal: {snap.error}")
    assets = snap.assets_sats
    liabilities = _liabilities(snap)  # incl. in-flight sends (conservative; H2/M1)
    onchain = snap.onchain_confirmed_sats
    amount = body.amount_sats
    reserve = twd.fee_reserve_for(body.sat_per_vbyte)

    # Guard 1: the on-chain wallet must hold the amount + the fee reserve.
    # (Guard failures raise BEFORE any record is written, so the Idempotency-Key
    # is reusable once liquidity recovers — they are not cached as terminal.)
    if amount + reserve > onchain:
        raise InvalidInput(
            f"Insufficient on-chain balance: {onchain} sats confirmed, "
            f"need {amount} + {reserve} fee reserve."
        )
    # Guard 2: SOLVENCY — assets after the send must still cover liabilities.
    if assets - amount - reserve < liabilities:
        raise InvalidInput(
            f"Withdrawal would breach solvency: assets {assets} - {amount} "
            f"- {reserve} fee < liabilities {liabilities}. Max withdrawable "
            f"now: {_withdrawable(assets, liabilities, onchain, reserve)} sats."
        )

    # Durable PENDING record (with the idempotency key) BEFORE the irreversible
    # broadcast, so a crash in the broadcast window leaves a reconcilable record.
    try:
        wid = await twd.record_pending(
            amount, body.address, body.sat_per_vbyte, reserve, idem_key
        )
    except IntegrityError as e:
        # Only a unique idem_key collision (a concurrent duplicate that won the
        # insert race) is a conflict; other DB errors propagate as 5xx.
        raise IdempotencyConflict(
            "A withdrawal with this Idempotency-Key is already in progress.",
            in_progress=True,
        ) from e
    log.info(
        "treasury.withdraw.start",
        withdrawal_id=wid,
        amount_sats=amount,
        address=body.address,
        assets_sats=assets,
        liabilities_sats=liabilities,
    )
    try:
        sent = await lnd.send_coins(body.address, amount, body.sat_per_vbyte)
    except Exception as e:  # noqa: BLE001 - AMBIGUOUS: may have broadcast
        # The send raised. We CANNOT tell whether LND broadcast before the error
        # (a timeout/drop after broadcast looks identical to a pre-broadcast
        # rejection). Terminalize to `unknown` (NOT `failed`) so a same-key retry
        # 409s instead of re-broadcasting — never double-spend. Operator
        # reconciles against the chain by amount+address.
        await twd.mark_unknown(wid, str(e))
        log.warning("treasury.withdraw.unknown_state", withdrawal_id=wid, error=str(e))
        raise

    # PAST THE POINT OF NO RETURN: the send is broadcast. From here NOTHING may
    # raise — a bookkeeping failure must not turn a real spend into an error
    # response (which idempotency/clients would read as "it didn't happen").
    log.info("treasury.withdraw.broadcast", withdrawal_id=wid, txid=sent.txid)
    assets_after, liabilities_after, withdrawable = await _remaining(session, lnd)
    ok = await twd.mark_broadcast(wid, sent.txid, assets_after, liabilities_after)
    if not ok:
        log.error("treasury.withdraw.record_update_failed", withdrawal_id=wid, txid=sent.txid)
    return WithdrawOut(
        withdrawal_id=wid,
        txid=sent.txid,
        amount_sats=amount,
        address=body.address,
        status="broadcast",
        assets_sats=assets_after,
        agent_liabilities_sats=liabilities_after,
        withdrawable_sats_remaining=withdrawable,
    )
