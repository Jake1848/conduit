from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import mint_api_key, require_scope
from ..db import get_session
from ..schemas import APIKeyCreateIn, APIKeyOut

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
