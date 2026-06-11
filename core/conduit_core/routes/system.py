from fastapi import APIRouter, Depends, Response
from sqlalchemy import text

from .. import __version__
from ..auth import require_scope
from ..config import get_settings
from ..db import SessionLocal
from ..schemas import ComponentHealth, HealthOut, ReadyOut, StatusOut
from ..services.lnd import get_lnd
from ..services.solvency import latest_snapshot

router = APIRouter(prefix="/v1", tags=["system"])


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    """Liveness: the process is up and serving. Intentionally does no I/O so a
    transient DB/LND blip never restart-loops the container."""
    s = get_settings()
    return HealthOut(ok=True, version=__version__, network=s.network)


@router.get("/health/ready", response_model=ReadyOut)
async def ready(response: Response) -> ReadyOut:
    """Readiness: checks the dependencies the money path actually needs. The DB is
    a hard dependency (→ 503 if down); LND is reported but not fatal."""
    s = get_settings()
    components: dict[str, ComponentHealth] = {}

    db_ok = True
    db_detail: str | None = None
    try:
        async with SessionLocal() as sess:
            await sess.execute(text("SELECT 1"))
    except Exception as e:  # noqa: BLE001 - report, never raise from a probe
        db_ok = False
        db_detail = type(e).__name__
    components["database"] = ComponentHealth(ok=db_ok, detail=db_detail)

    lnd_ok = True
    lnd_detail: str | None = None
    try:
        info = await get_lnd().get_info()
        if not info.synced_to_chain:
            lnd_detail = "not_synced_to_chain"
    except Exception as e:  # noqa: BLE001
        lnd_ok = False
        lnd_detail = type(e).__name__
    components["lnd"] = ComponentHealth(ok=lnd_ok, detail=lnd_detail)

    # Solvency — SOFT component: reflects whether the operator's node liquidity
    # currently backs the agent ledger. Does NOT 503 by default (a transient dip
    # while liquidity reshuffles shouldn't restart-loop the API); it surfaces the
    # state so an operator's monitoring can alert. Reads the monitor's latest
    # snapshot — `ok=True` until the first pass lands (nothing to back yet).
    snap = latest_snapshot()
    if snap is None:
        components["solvency"] = ComponentHealth(ok=True, detail="no_snapshot_yet")
    else:
        sol_detail: str | None = None
        if snap.error is not None:
            sol_detail = f"lnd_balance_error:{snap.error}"
        elif not snap.solvent:
            sol_detail = (
                f"insolvent:liabilities={snap.liabilities_sats},assets={snap.assets_sats}"
            )
        components["solvency"] = ComponentHealth(ok=snap.solvent, detail=sol_detail)

    overall = db_ok  # DB down = genuinely not ready; LND/solvency are surfaced only.
    if not overall:
        response.status_code = 503
    return ReadyOut(
        ok=overall, version=__version__, network=s.network, components=components
    )


@router.get("/status", response_model=StatusOut)
async def status(_=Depends(require_scope("admin"))) -> StatusOut:
    # Operator-only: exposes node identity + on-chain/channel liquidity, which is
    # the same operator-sensitive data the /metrics endpoint is edge-blocked for.
    # A read-scoped data-plane key must not see node liquidity.
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
