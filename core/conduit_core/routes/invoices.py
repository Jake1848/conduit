from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_scope
from ..db import get_session
from ..db.models import Agent, Transaction
from ..errors import AgentNotFound, NotFound
from ..schemas import InvoiceCreateIn, InvoiceOut
from ..services.ids import invoice_id as new_invoice_id
from ..services.lnd import get_lnd

router = APIRouter(prefix="/v1/invoices", tags=["invoices"])


@router.post("", response_model=InvoiceOut, status_code=201)
async def create_invoice(
    body: InvoiceCreateIn,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("write")),
) -> InvoiceOut:
    agent = await session.get(Agent, body.agent_id)
    if agent is None:
        raise AgentNotFound(f"No agent with id {body.agent_id}")
    lnd = get_lnd()
    inv = await lnd.create_invoice(body.amount, body.memo or "", body.expiry)

    tx = Transaction(
        id=new_invoice_id(),
        agent_id=body.agent_id,
        direction="receive",
        amount_sats=body.amount,
        payment_hash=inv.payment_hash,
        payment_request=inv.payment_request,
        memo=body.memo,
        status="pending",
        destination=None,
    )
    session.add(tx)
    await session.commit()
    await session.refresh(tx)

    return InvoiceOut(
        id=tx.id,
        agent_id=body.agent_id,
        payment_request=inv.payment_request,
        payment_hash=inv.payment_hash,
        amount_sats=body.amount,
        memo=body.memo,
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(seconds=body.expiry),
        created_at=tx.created_at,
    )


@router.get("/{invoice_id}", response_model=InvoiceOut)
async def get_invoice(
    invoice_id: str,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("read")),
) -> InvoiceOut:
    tx = await session.get(Transaction, invoice_id)
    if tx is None or tx.direction != "receive":
        raise NotFound(f"No invoice with id {invoice_id}")
    return InvoiceOut(
        id=tx.id,
        agent_id=tx.agent_id,
        payment_request=tx.payment_request or "",
        payment_hash=tx.payment_hash or "",
        amount_sats=tx.amount_sats,
        memo=tx.memo,
        status=tx.status,  # type: ignore[arg-type]
        expires_at=tx.created_at + timedelta(seconds=3600),
        created_at=tx.created_at,
    )


@router.get("", response_model=list[InvoiceOut])
async def list_invoices(
    agent_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("read")),
) -> list[InvoiceOut]:
    q = select(Transaction).where(Transaction.direction == "receive")
    if agent_id:
        q = q.where(Transaction.agent_id == agent_id)
    q = q.order_by(Transaction.created_at.desc()).limit(limit)
    rows = (await session.execute(q)).scalars().all()
    return [
        InvoiceOut(
            id=t.id,
            agent_id=t.agent_id,
            payment_request=t.payment_request or "",
            payment_hash=t.payment_hash or "",
            amount_sats=t.amount_sats,
            memo=t.memo,
            status=t.status,  # type: ignore[arg-type]
            expires_at=t.created_at + timedelta(seconds=3600),
            created_at=t.created_at,
        )
        for t in rows
    ]
