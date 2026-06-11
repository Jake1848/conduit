"""Platform-fee revenue for the self-hosted operator.

Reports the operator's accumulated platform fees — the per-payment revenue charged
on top of each payment (see services/fees.py). Fees are only "collected" on a
SETTLED payment (failed payments are refunded in full). This is an accounting view
over transactions; the sats themselves are simply retained in the operator's own
LND node. The aggregation lives in services/fees.aggregate_fees (shared with the
treasury overview).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_scope
from ..db import get_session
from ..schemas import FeesOut
from ..services.fees import aggregate_fees

router = APIRouter(prefix="/v1", tags=["fees"])


@router.get("/fees", response_model=FeesOut)
async def fees(
    session: AsyncSession = Depends(get_session),
    _=Depends(require_scope("admin")),
) -> FeesOut:
    return await aggregate_fees(session)
