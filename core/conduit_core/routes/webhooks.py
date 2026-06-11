import json
import secrets

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_scope
from ..db import get_session
from ..db.models import Webhook
from ..errors import NotFound
from ..schemas import WebhookIn, WebhookOut
from ..services.ids import webhook_id as new_webhook_id
from ..services.safe_http import assert_safe_url_shallow

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


@router.post("", response_model=WebhookOut, status_code=201)
async def create_webhook(
    body: WebhookIn,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("admin")),
) -> WebhookOut:
    # Validate the destination at creation time (https-only; reject literal
    # internal/metadata IPs) WITHOUT a DNS lookup, so a valid endpoint isn't
    # rejected for transient DNS failures. Delivery still does the authoritative
    # resolve + IP-pin (safe_post). Raises 422.
    assert_safe_url_shallow(body.url)
    secret = "whsec_" + secrets.token_urlsafe(32)
    wh = Webhook(
        id=new_webhook_id(),
        url=body.url,
        events=json.dumps(body.events),
        secret=secret,
    )
    session.add(wh)
    await session.commit()
    await session.refresh(wh)
    return WebhookOut(
        id=wh.id,
        url=wh.url,
        events=body.events,
        secret=secret,  # shown once
        active=wh.active,
        created_at=wh.created_at,
    )


@router.get("", response_model=list[WebhookOut])
async def list_webhooks(
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("admin")),
) -> list[WebhookOut]:
    rows = (await session.execute(select(Webhook))).scalars().all()
    return [
        WebhookOut(
            id=r.id,
            url=r.url,
            events=json.loads(r.events),
            secret=None,
            active=r.active,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(
    webhook_id: str,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("admin")),
) -> None:
    wh = await session.get(Webhook, webhook_id)
    if wh is None:
        raise NotFound(f"No webhook with id {webhook_id}")
    await session.delete(wh)
    await session.commit()
