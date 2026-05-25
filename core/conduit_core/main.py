import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .auth import ensure_bootstrap_key
from .config import get_settings
from .db import SessionLocal, init_db
from .routes import (
    agents,
    invoices,
    keys,
    payments,
    policies,
    system,
    transactions,
    webhooks,
)
from .services.lnd import get_lnd, shutdown_lnd


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
    log.info(
        "conduit_starting",
        version=__version__,
        env=settings.env,
        network=settings.network,
        lnd_mock=settings.lnd_mock,
    )
    await init_db()
    async with SessionLocal() as s:
        await ensure_bootstrap_key(s)
    get_lnd()  # warm singleton
    try:
        yield
    finally:
        await shutdown_lnd()
        log.info("conduit_stopped")


app = FastAPI(
    title="Conduit Core API",
    version=__version__,
    description="Bitcoin Lightning payment infrastructure for autonomous AI agents.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)
app.include_router(keys.router)
app.include_router(agents.router)
app.include_router(policies.router)
app.include_router(payments.router)
app.include_router(invoices.router)
app.include_router(transactions.router)
app.include_router(webhooks.router)
