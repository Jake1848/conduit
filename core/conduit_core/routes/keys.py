from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import mint_api_key, require_scope
from ..db import get_session
from ..db.models import APIKey
from ..errors import NotFound
from ..schemas import APIKeyCreateIn, APIKeyListItem, APIKeyListOut, APIKeyOut

router = APIRouter(prefix="/v1/api-keys", tags=["api-keys"])


@router.post("", response_model=APIKeyOut, status_code=201)
async def create_key(
    body: APIKeyCreateIn,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("admin")),
) -> APIKeyOut:
    raw, row = mint_api_key(scope=body.scope)
    row.label = body.label
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return APIKeyOut(
        id=row.id,
        label=row.label,
        scope=row.scope,  # type: ignore[arg-type]
        secret=raw,
        created_at=row.created_at,
    )


@router.get("", response_model=APIKeyListOut)
async def list_keys(
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("admin")),
) -> APIKeyListOut:
    """List all API keys (admin-only). The raw secret is never returned;
    use the value captured at creation time."""
    rows = (
        await session.execute(select(APIKey).order_by(APIKey.created_at.desc()))
    ).scalars().all()
    return APIKeyListOut(
        data=[
            APIKeyListItem(
                id=r.id,
                label=r.label,
                scope=r.scope,  # type: ignore[arg-type]
                prefix=r.prefix,
                created_at=r.created_at,
                last_used_at=r.last_used_at,
                revoked=r.revoked,
            )
            for r in rows
        ]
    )


@router.delete("/{key_id}", status_code=204)
async def revoke_key(
    key_id: str,
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("admin")),
) -> None:
    """Revoke an API key. The next request authenticating with it returns 401.

    Idempotent — calling on an already-revoked key is a no-op 204.
    """
    row = await session.get(APIKey, key_id)
    if row is None:
        raise NotFound(f"No API key with id {key_id}")
    if not row.revoked:
        row.revoked = True
        await session.commit()
