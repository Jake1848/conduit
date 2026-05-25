import json
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_scope
from ..db import get_session
from ..db.models import Agent, Policy, Transaction
from ..errors import (
    AgentNotFound,
    InsufficientBalance,
    InvalidInput,
    PaymentFailed,
    PolicyViolation,
)
from ..schemas import PaymentPayIn, PaymentSendIn, ReceiptOut
from ..services.ids import tx_id as new_tx_id
from ..services.lnd import get_lnd
from ..services.policy_engine import PaymentRequest, PolicyEngine
from ..services.wallet import (
    is_bolt11,
    is_lightning_address,
    resolve_lightning_address_to_invoice,
)
from ..services.webhook_sender import deliver

router = APIRouter(prefix="/v1/payments", tags=["payments"])
log = structlog.get_logger(__name__)


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
) -> ReceiptOut:
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
            result = await lnd.keysend(dest_pubkey, sats, memo or "")
        else:
            raise InvalidInput("Either payment_request or dest_pubkey is required")
    except PaymentFailed as e:
        # ----- Phase 3a: failure → refund the full debit -----
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
        await deliver(
            session,
            "payment.failed",
            {
                "transaction_id": tx_id_local,
                "agent_id": agent_id,
                "amount_sats": sats,
                "reason": str(e.detail),
            },
        )
        raise

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

    await deliver(
        session,
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


@router.post("/send", response_model=ReceiptOut, status_code=201)
async def send_payment(
    body: PaymentSendIn,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("write")),
) -> ReceiptOut:
    if body.payment_request:
        if not is_bolt11(body.payment_request):
            raise InvalidInput("payment_request is not a BOLT11 invoice")
        decoded = await get_lnd().decode_invoice(body.payment_request)
        sats = body.sats or decoded.amount_sats
        if not sats:
            raise InvalidInput("Zero-amount invoice requires `sats` to be provided")
        return await _execute_payment(
            session=session,
            agent_id=body.agent_id,
            sats=sats,
            destination=body.payment_request,
            memo=body.memo,
            metadata=body.metadata,
            invoice=body.payment_request,
            dest_pubkey=decoded.destination,
        )
    if body.dest_pubkey:
        if not body.sats:
            raise InvalidInput("Keysend requires `sats`")
        return await _execute_payment(
            session=session,
            agent_id=body.agent_id,
            sats=body.sats,
            destination=body.dest_pubkey,
            memo=body.memo,
            metadata=body.metadata,
            invoice=None,
            dest_pubkey=body.dest_pubkey,
        )
    raise InvalidInput("Either payment_request or dest_pubkey is required")


@router.post("/pay", response_model=ReceiptOut, status_code=201)
async def pay(
    body: PaymentPayIn,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("write")),
) -> ReceiptOut:
    """Pay a Lightning address (`name@host`) or a BOLT11 invoice."""
    invoice: str | None = None
    dest_pubkey: str | None = None

    if is_lightning_address(body.to):
        invoice = await resolve_lightning_address_to_invoice(body.to, body.sats, body.memo)
        decoded = await get_lnd().decode_invoice(invoice)
        dest_pubkey = decoded.destination
    elif is_bolt11(body.to):
        invoice = body.to
        decoded = await get_lnd().decode_invoice(invoice)
        dest_pubkey = decoded.destination
    else:
        raise InvalidInput(f"Unsupported destination format: {body.to}")

    return await _execute_payment(
        session=session,
        agent_id=body.agent_id,
        sats=body.sats,
        destination=body.to,
        memo=body.memo,
        metadata=body.metadata,
        invoice=invoice,
        dest_pubkey=dest_pubkey,
    )


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
