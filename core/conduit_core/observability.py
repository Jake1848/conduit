"""Observability — Prometheus exposition + optional Sentry error reporting.

Two concerns, both deliberately graceful so the app boots even if the optional
libraries are missing (they are declared in pyproject, but a slimmed image or a
partial install shouldn't take the money path down):

  * Prometheus: a small set of process/business gauges + a request
    counter/latency histogram, exposed at the ROOT path GET /metrics (an OPS
    endpoint, distinct from the dashboard-facing JSON GET /v1/metrics). When
    prometheus_client is unavailable the endpoint returns a tiny plaintext
    fallback and the middleware degrades to a no-op.

  * Sentry: initialized ONLY when SENTRY_DSN is set. No DSN → complete no-op (no
    SDK touched, no network). Import failure is swallowed with a warning.

Nothing here raises into a request: a metrics-collection or Sentry hiccup must
never affect a payment.
"""

from __future__ import annotations

import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

log = structlog.get_logger(__name__)

# ---------- Prometheus (graceful) ----------

try:  # pragma: no cover - import wiring
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    _PROM_AVAILABLE = True
except Exception:  # noqa: BLE001 pragma: no cover
    _PROM_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"


# Use a dedicated registry rather than the global default so importing this module
# twice (e.g. across test reloads) can't raise "Duplicated timeseries". Built once
# at import time.
if _PROM_AVAILABLE:
    REGISTRY = CollectorRegistry()

    REQUEST_COUNT = Counter(
        "conduit_http_requests_total",
        "Total HTTP requests processed.",
        ["method", "path", "status"],
        registry=REGISTRY,
    )
    REQUEST_LATENCY = Histogram(
        "conduit_http_request_duration_seconds",
        "HTTP request latency in seconds.",
        ["method", "path"],
        registry=REGISTRY,
    )
    LND_SYNCED = Gauge(
        "conduit_lnd_synced_to_chain",
        "1 if LND reports synced_to_chain, else 0.",
        registry=REGISTRY,
    )
    CHANNEL_LOCAL_SATS = Gauge(
        "conduit_lnd_channel_local_sats",
        "Total local (outbound) channel balance in sats.",
        registry=REGISTRY,
    )
    ONCHAIN_CONFIRMED_SATS = Gauge(
        "conduit_lnd_onchain_confirmed_sats",
        "Confirmed on-chain wallet balance in sats.",
        registry=REGISTRY,
    )
    SOLVENCY_RATIO = Gauge(
        "conduit_solvency_ratio",
        "assets / liabilities. 1.0 == fully backed; <1.0 == insolvent.",
        registry=REGISTRY,
    )
    SOLVENCY_LIABILITIES = Gauge(
        "conduit_solvency_liabilities_sats",
        "Sum of agent balances + pending outbound (the operator's liabilities).",
        registry=REGISTRY,
    )
    SOLVENCY_ASSETS = Gauge(
        "conduit_solvency_assets_sats",
        "Channel-local + confirmed on-chain (the assets backing the ledger).",
        registry=REGISTRY,
    )
    SOLVENT = Gauge(
        "conduit_solvent",
        "1 if the ledger is currently backed by node liquidity, else 0.",
        registry=REGISTRY,
    )
    WORKER_LIVENESS = Gauge(
        "conduit_worker_seconds_since_last_run",
        "Seconds since a background worker last completed a cycle.",
        ["worker"],
        registry=REGISTRY,
    )


def _norm_path(request: Request) -> str:
    """Use the route TEMPLATE (e.g. /v1/agents/{agent_id}) not the raw path, so a
    per-id explosion of label values can't blow up cardinality."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path or request.url.path


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Counts requests + records latency. No-op when prometheus_client is absent."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if not _PROM_AVAILABLE:
            return await call_next(request)
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            elapsed = time.perf_counter() - start
            path = _norm_path(request)
            # Don't record the scrape of /metrics itself against itself.
            if path != "/metrics":
                try:
                    REQUEST_COUNT.labels(
                        request.method, path, str(status_code)
                    ).inc()
                    REQUEST_LATENCY.labels(request.method, path).observe(elapsed)
                except Exception:  # noqa: BLE001
                    pass


def _refresh_business_gauges(app) -> None:
    """Pull the latest cached values into the gauges right before a scrape.

    Reads the solvency snapshot (the monitor refreshes it on its own loop) and the
    background-worker liveness markers. Cheap and lock-free — never raises.
    """
    if not _PROM_AVAILABLE:
        return
    try:
        from .services import solvency as _solvency

        snap = _solvency.latest_snapshot()
        if snap is not None:
            SOLVENCY_LIABILITIES.set(snap.liabilities_sats)
            SOLVENCY_ASSETS.set(snap.assets_sats)
            CHANNEL_LOCAL_SATS.set(snap.channel_local_sats)
            ONCHAIN_CONFIRMED_SATS.set(snap.onchain_confirmed_sats)
            SOLVENT.set(1 if snap.solvent else 0)
            # Ratio gauge: None (no liabilities) reads as fully-backed → 1.0 floor
            # is misleading, so publish a large sentinel meaning "no liabilities".
            if snap.ratio is not None:
                SOLVENCY_RATIO.set(snap.ratio)
    except Exception as e:  # noqa: BLE001
        log.warning("prometheus_solvency_refresh_failed", error=str(e))

    # Worker liveness — seconds since each background worker last ran.
    try:
        now = time.monotonic()
        monitor = getattr(app.state, "solvency_monitor", None)
        last = getattr(monitor, "last_run_monotonic", None) if monitor else None
        if last is not None:
            WORKER_LIVENESS.labels("solvency_monitor").set(max(0.0, now - last))
    except Exception:  # noqa: BLE001
        pass


def set_lnd_synced(synced: bool) -> None:
    """Called from the LND-reachable boot probe (real-LND mode)."""
    if _PROM_AVAILABLE:
        try:
            LND_SYNCED.set(1 if synced else 0)
        except Exception:  # noqa: BLE001
            pass


async def metrics_endpoint(request: Request) -> Response:
    """GET /metrics — Prometheus exposition. ROOT path, unauthenticated (ops)."""
    if not _PROM_AVAILABLE:
        return PlainTextResponse(
            "# prometheus_client not installed; metrics unavailable\n",
            media_type="text/plain",
        )
    _refresh_business_gauges(request.app)
    data = generate_latest(REGISTRY)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


# ---------- Sentry (optional) ----------

def init_sentry(dsn: str | None, *, environment: str, release: str) -> bool:
    """Initialize Sentry iff a DSN is provided. Returns True if initialized.

    No DSN → no-op, returns False. Import/init failure is swallowed (logged) so a
    misconfigured Sentry can never block startup.
    """
    if not dsn:
        return False
    try:  # pragma: no cover - exercised only when a DSN + SDK are present
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            release=release,
            # Conservative defaults — errors only, no perf sampling by default.
            traces_sample_rate=0.0,
        )
        log.info("sentry_initialized", environment=environment, release=release)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("sentry_init_failed", error=str(e))
        return False
