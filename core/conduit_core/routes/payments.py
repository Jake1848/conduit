import json
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_scope
from ..db import get_session
from ..db.models import Agent, Policy, Transaction
from ..errors import AgentNotFound, InvalidInput, PaymentFailed, PolicyViolation
from ..schemas import PaymentPayIn, PaymentSendIn, ReceiptOut
from ..services.ids import tx_id as new_tx_id
from ..services.lnd import get_lnd
from ..services.policy_engine import (
    PaymentRequest,
    PolicyEngine,
    agent_payment_lock,
)
from ..services.wallet import (
    is_bolt11,
    is_lightning_address,
    resolve_lightning_address_to_invoice,
)
from ..services.webhook_sender import deliver

router = APIRouter(prefix="/v1/payments", tags=["payments"])
log = structlog.get_logger(__name__)


async def _load(session: AsyncSession, agent_id: str) -> tuple[Agent, Policy | None]:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise AgentNotFound(f"No agent with id {agent_id}")
    if not agent.active:
        raise PolicyViolation(f"Agent {agent_id} is inactive", code="AGENT_INACTIVE")
    policy = (
        await session.execute(select(Policy).where(Policy.agent_id == agent_id))
    ).scalar_one_or_none()
    return agent, policy


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
    agent, policy = await _load(session, agent_id)

    async with agent_payment_lock(agent_id):
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

        # Record a pending Transaction *before* talking to LND so concurrent
        # evaluations count it against the window.
        tx = Transaction(
            id=new_tx_id(),
            agent_id=agent_id,
            direction="send",
            amount_sats=sats,
            destination=destination,
            payment_request=invoice,
            status="pending",
            memo=memo,
            metadata_json=json.dumps(metadata) if metadata else None,
        )
        session.add(tx)
        await session.commit()
        await session.refresh(tx)

    lnd = get_lnd()
    try:
        if invoice:
            result = await lnd.pay_invoice(invoice, max_fee_sats=max(1, sats // 100))
        elif dest_pubkey:
            result = await lnd.keysend(dest_pubkey, sats, memo or "")
        else:
            raise InvalidInput("Either payment_request or dest_pubkey is required")
    except PaymentFailed as e:
        tx.status = "failed"
        tx.failure_reason = str(e.detail)
        await session.commit()
        await deliver(
            session,
            "payment.failed",
            {"transaction_id": tx.id, "agent_id": agent_id, "reason": str(e.detail)},
        )
        raise

    tx.status = "settled"
    tx.payment_hash = result.payment_hash
    tx.payment_preimage = result.payment_preimage
    tx.fee_sats = result.fee_sats
    tx.latency_ms = result.latency_ms
    tx.settled_at = datetime.now(timezone.utc)
    await session.commit()
    await deliver(
        session,
        "payment.settled",
        {
            "transaction_id": tx.id,
            "agent_id": agent_id,
            "amount_sats": tx.amount_sats,
            "fee_sats": tx.fee_sats,
            "hash": tx.payment_hash,
        },
    )
    return ReceiptOut(
        id=tx.id,
        agent_id=agent_id,
        status="settled",
        hash=tx.payment_hash,
        amount_sats=tx.amount_sats,
        fee_sats=tx.fee_sats,
        settled_in_ms=tx.latency_ms,
        destination=destination,
        memo=memo,
        created_at=tx.created_at,
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
