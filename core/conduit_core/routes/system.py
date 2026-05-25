from fastapi import APIRouter, Depends

from .. import __version__
from ..auth import require_scope
from ..config import get_settings
from ..schemas import HealthOut, StatusOut
from ..services.lnd import get_lnd

router = APIRouter(prefix="/v1", tags=["system"])


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    s = get_settings()
    return HealthOut(ok=True, version=__version__, network=s.network)


@router.get("/status", response_model=StatusOut)
async def status(_=Depends(require_scope("read"))) -> StatusOut:
    s = get_settings()
    lnd = get_lnd()
    info = await lnd.get_info()
    bal = await lnd.get_balance()
    return StatusOut(
        env=s.env,
        network=s.network,
        node={
            "alias": info.alias,
            "pubkey": info.pubkey,
            "block_height": info.block_height,
            "synced_to_chain": info.synced_to_chain,
        },
        balance={
            "confirmed_sats": bal.confirmed_sats,
            "unconfirmed_sats": bal.unconfirmed_sats,
            "channel_local_sats": bal.channel_local_sats,
            "channel_remote_sats": bal.channel_remote_sats,
        },
        channels={"num_active": info.num_active_channels},
    )
