import hashlib
import json
import secrets
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_scope
from ..db import get_session
from ..db.models import Agent, APIKey, Policy, Transaction
from ..errors import (
    AgentNotFound,
    ConduitError,
    InsufficientBalance,
    InvalidInput,
    PaymentFailed,
    PolicyViolation,
)
from ..schemas import PaymentPayIn, PaymentSendIn, ReceiptOut
from ..services import idempotency
from ..services.ids import tx_id as new_tx_id
from ..services.lnd import get_lnd
from ..services.policy_engine import PaymentRequest, PolicyEngine
from ..services.wallet import (
    is_bolt11,
    is_lightning_address,
    resolve_lightning_address_to_invoice,
)
from ..services.webhook_sender import fire as fire_webhook

router = APIRouter(prefix="/v1/payments", tags=["payments"])
log = structlog.get_logger(__name__)


async def _idempotent(
    request: Request,
    session: AsyncSession,
    api_key: APIKey,
    body: BaseModel,
    run: Any,  # callable returning a ReceiptOut
):
    """Wrap a payment handler with idempotency-key caching.

    If the caller sent `Idempotency-Key`, we cache the response (success
    OR failure) so a retry returns the same outcome without re-executing.
    """
    idem_key = request.headers.get("Idempotency-Key", "")
    if not idem_key.strip():
        return await run()

    # Read api_key.id NOW (eagerly to a local string). Once a payment
    # raises and the request session is rolled back, accessing detached
    # ORM attributes triggers a lazy load → MissingGreenlet from aiosqlite.
    api_key_id = api_key.id

    key = idempotency.validate_key(idem_key)
    request_hash = idempotency.hash_payload(body)

    cached = await idempotency.lookup(session, api_key_id, key, request_hash)
    if cached is not None:
        return JSONResponse(content=cached.body, status_code=cached.status_code)

    try:
        receipt = await run()
    except ConduitError as e:
        # Cache failure responses too — Stripe-style. Otherwise a flapping
        # network would let retries hit the live execution path repeatedly.
        await idempotency.store(
            session,
            api_key_id,
            key,
            request_hash,
            status_code=e.status_code,
            body={"detail": e.detail},
        )
        raise

    payload = receipt.model_dump(mode="json") if isinstance(receipt, BaseModel) else receipt
    await idempotency.store(
        session,
        api_key_id,
        key,
        request_hash,
        status_code=201,
        body=payload,
    )
    return receipt


def _estimate_max_fee_sats(sats: int) -> int:
    """Conservative routing fee budget: 1% with a 1-sat floor."""
    return max(1, sats // 100)


async def _execute_payment(
    session: AsyncSession,
    agent_id: str,
    sats: int,
    destination: str,
    memo: str | None,
    metadata: dict | None,
    invoice: str | None,
    dest_pubkey: str | None,
    *,
    payment_hash: str,
    keysend_preimage: bytes | None = None,
) -> ReceiptOut:
    """Run a payment.

    `payment_hash` MUST be known up-front and is stored on the pending row
    so the reconciler can identify the payment in LND after a crash/timeout.
    For BOLT11 we get it from `decode_invoice`; for keysend the caller
    pre-generates a preimage and derives the hash from it (and passes the
    same preimage in `keysend_preimage` so LND uses it).
    """
    fee_budget = _estimate_max_fee_sats(sats)
    debit_total = sats + fee_budget

    # ----- Phase 1: locked decision + debit + pending row -----
    # SQLAlchemy 2.0 implicitly begins a transaction on the first query.
    # The row lock from with_for_update() is held until commit().
    try:
        agent_row = await session.execute(
            select(Agent).where(Agent.id == agent_id).with_for_update()
        )
        agent = agent_row.scalar_one_or_none()
        if agent is None:
            raise AgentNotFound(f"No agent with id {agent_id}")
        if not agent.active:
            raise PolicyViolation(f"Agent {agent_id} is inactive", code="AGENT_INACTIVE")

        policy_row = await session.execute(
            select(Policy).where(Policy.agent_id == agent_id)
        )
        policy = policy_row.scalar_one_or_none()

        engine = PolicyEngine(session)
        decision = await engine.evaluate(
            policy,
            PaymentRequest(
                agent_id=agent_id,
                sats=sats,
                destination=destination,
                memo=memo,
                dest_pubkey=dest_pubkey,
            ),
        )
        if not decision.allowed:
            log.warning(
                "policy_violation",
                agent_id=agent_id,
                code=decision.code,
                sats=sats,
                destination=destination,
            )
            raise PolicyViolation(
                decision.detail,
                code=decision.code,
                agent_id=agent_id,
                used_hour_sats=decision.used_hour_sats,
                used_day_sats=decision.used_day_sats,
                minute_count=decision.minute_count,
            )

        if (agent.balance_sats or 0) < debit_total:
            raise InsufficientBalance(
                f"Agent balance {agent.balance_sats} sats < required {debit_total} "
                f"({sats} + {fee_budget} fee budget). Credit the agent via "
                f"POST /v1/agents/{agent_id}/credit before retrying.",
                agent_id=agent_id,
                balance_sats=agent.balance_sats or 0,
                required_sats=debit_total,
            )

        agent.balance_sats -= debit_total

        tx = Transaction(
            id=new_tx_id(),
            agent_id=agent_id,
            direction="send",
            amount_sats=sats,
            fee_sats=fee_budget,  # reserved budget; corrected to actual on settle
            destination=destination,
            payment_request=invoice,
            payment_hash=payment_hash,  # known up-front so reconciler can find it
            status="pending",
            memo=memo,
            metadata_json=json.dumps(metadata) if metadata else None,
        )
        session.add(tx)
        await session.commit()  # releases the row lock
    except Exception:
        await session.rollback()
        raise

    await session.refresh(tx)
    tx_id_local = tx.id
    created_at = tx.created_at

    # ----- Phase 2: contact LND outside the lock -----
    lnd = get_lnd()
    try:
        if invoice:
            result = await lnd.pay_invoice(invoice, max_fee_sats=fee_budget)
        elif dest_pubkey:
            result = await lnd.keysend(
                dest_pubkey, sats, memo or "", preimage=keysend_preimage
            )
        else:
            raise InvalidInput("Either payment_request or dest_pubkey is required")
    except PaymentFailed as e:
        # ----- Phase 3a: definite failure → refund the full debit -----
        try:
            refund_agent = (
                await session.execute(
                    select(Agent).where(Agent.id == agent_id).with_for_update()
                )
            ).scalar_one()
            refund_agent.balance_sats += debit_total
            failed_tx = await session.get(Transaction, tx_id_local)
            assert failed_tx is not None
            failed_tx.status = "failed"
            failed_tx.failure_reason = str(e.detail)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        fire_webhook(
            "payment.failed",
            {
                "transaction_id": tx_id_local,
                "agent_id": agent_id,
                "amount_sats": sats,
                "reason": str(e.detail),
            },
        )
        raise
    except Exception as e:  # noqa: BLE001
        # ----- Phase 3c: UNKNOWN state — don't refund.
        # The payment may have actually settled on LND while our HTTP call
        # failed (timeout, 5xx, parse error, lost connection, etc.). Refunding
        # here would let the agent spend twice — once via the in-flight LND
        # settlement and once via the refunded balance. We mark the row with
        # a reconciliation marker and surface a clear error.
        log.critical(
            "payment_unknown_state",
            tx_id=tx_id_local,
            agent_id=agent_id,
            sats=sats,
            destination=destination,
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        try:
            unknown_tx = await session.get(Transaction, tx_id_local)
            if unknown_tx is not None:
                unknown_tx.failure_reason = (
                    f"needs_reconciliation: {type(e).__name__}: {e}"
                )
                await session.commit()
        except Exception:
            await session.rollback()
        raise PaymentFailed(
            "Payment to LND ended in an UNKNOWN state — the Lightning payment "
            "may or may not have settled. Balance has NOT been refunded to "
            "prevent double-spend. Reconcile transaction "
            f"{tx_id_local} (call LND `lookuppayment`) before issuing a new "
            f"payment to the same destination. Underlying error: {type(e).__name__}: {e}",
            transaction_id=tx_id_local,
            needs_reconciliation=True,
            underlying_error=type(e).__name__,
        ) from e

    # ----- Phase 3b: success → reconcile fee budget vs actual fee -----
    actual_fee = max(0, int(result.fee_sats))
    fee_refund = max(0, fee_budget - actual_fee)
    try:
        settle_agent = (
            await session.execute(
                select(Agent).where(Agent.id == agent_id).with_for_update()
            )
        ).scalar_one()
        if fee_refund > 0:
            settle_agent.balance_sats += fee_refund
        settled_tx = await session.get(Transaction, tx_id_local)
        assert settled_tx is not None
        settled_tx.status = "settled"
        settled_tx.payment_hash = result.payment_hash
        settled_tx.payment_preimage = result.payment_preimage
        settled_tx.fee_sats = actual_fee
        settled_tx.latency_ms = result.latency_ms
        settled_tx.settled_at = datetime.now(UTC)
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    fire_webhook(
        "payment.settled",
        {
            "transaction_id": tx_id_local,
            "agent_id": agent_id,
            "amount_sats": sats,
            "fee_sats": actual_fee,
            "hash": result.payment_hash,
        },
    )
    return ReceiptOut(
        id=tx_id_local,
        agent_id=agent_id,
        status="settled",
        hash=result.payment_hash,
        amount_sats=sats,
        fee_sats=actual_fee,
        settled_in_ms=result.latency_ms,
        destination=destination,
        memo=memo,
        created_at=created_at,
    )


def _resolve_bolt11_amount(decoded_amount_sats: int, requested_sats: int | None) -> int:
    """Determine the authoritative payment amount for a BOLT11 invoice.

    SECURITY: a BOLT11 invoice has an embedded amount. The caller may also
    supply `sats`. We do NOT silently prefer one over the other — that's
    how an attacker pays a 1,000,000-sat invoice with a 1-sat budget. The
    only safe behaviors are:

      - Fixed-amount invoice + no `sats` provided  → use the invoice amount.
      - Fixed-amount invoice + `sats` matches      → use the invoice amount.
      - Fixed-amount invoice + `sats` differs      → REJECT.
      - Zero-amount invoice + `sats` provided      → use `sats`.
      - Zero-amount invoice + no `sats`            → REJECT.
    """
    if decoded_amount_sats > 0:
        if requested_sats is not None and requested_sats != decoded_amount_sats:
            raise InvalidInput(
                f"Invoice amount ({decoded_amount_sats} sats) does not match the "
                f"requested `sats` ({requested_sats}). Either omit `sats` or set it "
                "to the invoice amount.",
                invoice_amount_sats=decoded_amount_sats,
                requested_sats=requested_sats,
            )
        return decoded_amount_sats
    if not requested_sats:
        raise InvalidInput("Zero-amount invoice requires `sats` to be provided")
    return requested_sats


@router.post("/send", status_code=201)
async def send_payment(
    body: PaymentSendIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
    api_key: APIKey = Depends(require_scope("write")),
):
    async def run() -> ReceiptOut:
        if body.payment_request:
            if not is_bolt11(body.payment_request):
                raise InvalidInput("payment_request is not a BOLT11 invoice")
            decoded = await get_lnd().decode_invoice(body.payment_request)
            sats = _resolve_bolt11_amount(decoded.amount_sats, body.sats)
            return await _execute_payment(
                session=session,
                agent_id=body.agent_id,
                sats=sats,
                destination=body.payment_request,
                memo=body.memo,
                metadata=body.metadata,
                invoice=body.payment_request,
                dest_pubkey=decoded.destination,
                payment_hash=decoded.payment_hash,
            )
        if body.dest_pubkey:
            if not body.sats:
                raise InvalidInput("Keysend requires `sats`")
            # Pre-generate the preimage so we know the payment_hash up-front.
            # We pass the SAME preimage to LND so the on-network payment hash
            # matches what we recorded.
            preimage = secrets.token_bytes(32)
            payment_hash = hashlib.sha256(preimage).hexdigest()
            return await _execute_payment(
                session=session,
                agent_id=body.agent_id,
                sats=body.sats,
                destination=body.dest_pubkey,
                memo=body.memo,
                metadata=body.metadata,
                invoice=None,
                dest_pubkey=body.dest_pubkey,
                payment_hash=payment_hash,
                keysend_preimage=preimage,
            )
        raise InvalidInput("Either payment_request or dest_pubkey is required")

    return await _idempotent(request, session, api_key, body, run)


@router.post("/pay", status_code=201)
async def pay(
    body: PaymentPayIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
    api_key: APIKey = Depends(require_scope("write")),
):
    """Pay a Lightning address (`name@host`) or a BOLT11 invoice."""

    async def run() -> ReceiptOut:
        invoice: str | None = None
        dest_pubkey: str | None = None
        payment_hash: str | None = None

        if is_lightning_address(body.to):
            invoice = await resolve_lightning_address_to_invoice(
                body.to, body.sats, body.memo
            )
            decoded = await get_lnd().decode_invoice(invoice)
            # SECURITY: LNURL-pay servers can return an invoice for a different
            # amount than we asked for. Refuse to pay anything other than what
            # the caller authorized.
            if decoded.amount_sats > 0 and decoded.amount_sats != body.sats:
                raise PaymentFailed(
                    f"Lightning address {body.to} returned an invoice for "
                    f"{decoded.amount_sats} sats but we requested {body.sats}. "
                    "Refusing to pay — verify the destination.",
                    lightning_address=body.to,
                    invoice_amount_sats=decoded.amount_sats,
                    requested_sats=body.sats,
                )
            dest_pubkey = decoded.destination
            payment_hash = decoded.payment_hash
        elif is_bolt11(body.to):
            invoice = body.to
            decoded = await get_lnd().decode_invoice(invoice)
            # Same defense as /send for BOLT11.
            sats_to_use = _resolve_bolt11_amount(decoded.amount_sats, body.sats)
            if sats_to_use != body.sats:
                raise InvalidInput(
                    f"`to` is a BOLT11 invoice for {decoded.amount_sats} sats but "
                    f"`sats`={body.sats}. They must match."
                )
            dest_pubkey = decoded.destination
            payment_hash = decoded.payment_hash
        else:
            raise InvalidInput(f"Unsupported destination format: {body.to}")

        assert payment_hash is not None  # set in every branch above
        return await _execute_payment(
            session=session,
            agent_id=body.agent_id,
            sats=body.sats,
            destination=body.to,
            memo=body.memo,
            metadata=body.metadata,
            invoice=invoice,
            dest_pubkey=dest_pubkey,
            payment_hash=payment_hash,
        )

    return await _idempotent(request, session, api_key, body, run)


@router.get("/{payment_id}", response_model=ReceiptOut)
async def get_payment(
    payment_id: str,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("read")),
) -> ReceiptOut:
    tx = await session.get(Transaction, payment_id)
    if tx is None or tx.direction != "send":
        raise InvalidInput(f"No payment with id {payment_id}")
    return ReceiptOut(
        id=tx.id,
        agent_id=tx.agent_id,
        status=tx.status,  # type: ignore[arg-type]
        hash=tx.payment_hash,
        amount_sats=tx.amount_sats,
        fee_sats=tx.fee_sats,
        settled_in_ms=tx.latency_ms,
        destination=tx.destination,
        memo=tx.memo,
        created_at=tx.created_at,
    )
