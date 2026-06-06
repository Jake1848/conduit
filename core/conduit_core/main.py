import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .auth import ensure_bootstrap_key
from .config import get_settings
from .db import SessionLocal, init_db
from .errors import ConduitError
from .middleware import RateLimitMiddleware, RequestContextMiddleware
from .routes import (
    agents,
    fees,
    invoices,
    keys,
    metrics,
    payments,
    policies,
    system,
    transactions,
    webhooks,
)
from .services import webhook_sender
from .services.invoice_watcher import InvoiceWatcher
from .services.lnd import get_lnd, shutdown_lnd
from .services.maintenance import IdempotencyPruner
from .services.reconciler import PaymentReconciler


def _configure_logging(level: str) -> None:
    logging.basicConfig(format="%(message)s", level=level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level.upper())
        ),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    _configure_logging(settings.log_level)
    log = structlog.get_logger(__name__)

    # Refuse to start with insecure defaults in production.
    errors = settings.validate_for_runtime()
    if errors:
        for e in errors:
            log.error("startup_config_error", error=e)
        raise SystemExit(
            "Conduit refuses to start: production safety check failed.\n  - "
            + "\n  - ".join(errors)
        )

    log.info(
        "conduit_starting",
        version=__version__,
        env=settings.env,
        network=settings.network,
        lnd_mock=settings.lnd_mock,
        database_dialect=settings.database_url.split(":", 1)[0],
        allowed_origins=settings.allowed_origins,
        rate_limit_per_minute=settings.rate_limit_per_minute,
    )

    await init_db()
    async with SessionLocal() as s:
        await ensure_bootstrap_key(s)

    # Retention prune for idempotency rows — runs in every mode (the table fills
    # regardless of whether LND is mocked).
    pruner = IdempotencyPruner(
        SessionLocal,
        retention_hours=settings.idempotency_retention_hours,
        interval_seconds=settings.idempotency_prune_interval_seconds,
    )
    await pruner.start()
    app.state.idempotency_pruner = pruner

    lnd = get_lnd()
    watcher: InvoiceWatcher | None = None
    reconciler: PaymentReconciler | None = None
    # If we're meant to be talking to a real LND, fail fast at boot rather
    # than discovering it on the first payment.
    if not settings.lnd_mock:
        try:
            info = await lnd.get_info()
            log.info(
                "lnd_reachable",
                alias=info.alias,
                pubkey=info.pubkey,
                block_height=info.block_height,
                synced=info.synced_to_chain,
            )
            if not info.synced_to_chain:
                log.warning("lnd_not_synced_to_chain")
        except Exception as e:  # noqa: BLE001
            log.error("lnd_unreachable", error=str(e))
            raise SystemExit(
                f"Conduit cannot reach LND at {settings.lnd_rest_url}: {e}. "
                "Check LND_REST_URL, LND_MACAROON_PATH, LND_TLS_CERT_PATH, "
                "and that LND is unlocked."
            ) from e

        # Start the invoice settlement watcher — only with real LND. In mock
        # mode there's no stream to read; tests drive process_update() directly.
        watcher = InvoiceWatcher(lnd, SessionLocal)
        await watcher.start()
        app.state.invoice_watcher = watcher

        # Reconciler closes the loop on pending sends whose LND HTTP call
        # ended in an unknown state. Only meaningful against real LND.
        reconciler = PaymentReconciler(lnd, SessionLocal)
        await reconciler.start()
        app.state.payment_reconciler = reconciler

    try:
        yield
    finally:
        await pruner.stop()
        if reconciler is not None:
            await reconciler.stop()
        if watcher is not None:
            await watcher.stop()
        # Drain in-flight webhook deliveries before shutting LND down.
        await webhook_sender.flush(timeout=10.0)
        await shutdown_lnd()
        log.info("conduit_stopped")


app = FastAPI(
    title="Conduit Core API",
    version=__version__,
    description="Bitcoin Lightning payment infrastructure for autonomous AI agents.",
    lifespan=lifespan,
)

_settings = get_settings()

# CORS — explicit allowlist only. Empty list = no cross-origin requests.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.allowed_origins,
    allow_credentials=bool(_settings.allowed_origins),
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)

# In-process token-bucket rate limiter. See middleware.py for the worker caveat.
app.add_middleware(RateLimitMiddleware, settings=_settings)

# Outermost (added last): stamp a request id and bind it into the log context
# before any other middleware runs, so even a rate-limit rejection is traceable.
app.add_middleware(RequestContextMiddleware)


@app.exception_handler(ConduitError)
async def _conduit_error_handler(_: Request, exc: ConduitError) -> JSONResponse:
    # Let our typed ConduitError flow through with its structured detail body.
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def _unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    # Catch-all so a crash on a payment path returns structured JSON, not HTML.
    # Logged with traceback for debugging. The user-facing detail is generic;
    # internals don't leak through the wire.
    structlog.get_logger(__name__).exception("unhandled_exception", error=str(exc))
    return JSONResponse(
        status_code=500,
        content={
            "detail": {
                "error": "internal_error",
                "code": "INTERNAL_ERROR",
                "detail": "An unexpected error occurred. The incident has been logged.",
            }
        },
    )


app.include_router(system.router)
app.include_router(keys.router)
app.include_router(agents.router)
app.include_router(policies.router)
app.include_router(payments.router)
app.include_router(invoices.router)
app.include_router(transactions.router)
app.include_router(webhooks.router)
app.include_router(metrics.router)
app.include_router(fees.router)
