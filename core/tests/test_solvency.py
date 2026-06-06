"""Solvency monitor + reliability/observability surface.

Covers:
  * compute_solvency math against a mocked LND balance (liabilities vs assets)
  * the snapshot is surfaced on /v1/metrics and /v1/health/ready
  * enforce_solvent() fails closed only when configured + insolvent
  * the agents.balance_sats >= 0 DB CHECK rejects a negative write
  * GET /metrics returns Prometheus exposition (or the graceful fallback)
"""

from dataclasses import dataclass

import pytest

from conduit_core.services import solvency as solvency_mod
from conduit_core.services.solvency import (
    SolvencyError,
    SolvencyMonitor,
    compute_solvency,
    enforce_solvent,
    latest_snapshot,
)


@dataclass
class _FakeBalance:
    confirmed_sats: int
    unconfirmed_sats: int
    channel_local_sats: int
    channel_remote_sats: int


class _FakeLND:
    """Minimal LND stand-in exposing only get_balance(), which is all the
    solvency monitor needs."""

    def __init__(self, *, channel_local: int, confirmed: int, raise_exc: bool = False):
        self._channel_local = channel_local
        self._confirmed = confirmed
        self._raise = raise_exc

    async def get_balance(self) -> _FakeBalance:
        if self._raise:
            raise RuntimeError("lnd down")
        return _FakeBalance(
            confirmed_sats=self._confirmed,
            unconfirmed_sats=0,
            channel_local_sats=self._channel_local,
            channel_remote_sats=0,
        )


@pytest.fixture(autouse=True)
def _clear_solvency_cache():
    # Each test starts with no published snapshot.
    solvency_mod.reset_cache()
    yield
    solvency_mod.reset_cache()


# ---------- computation ----------

@pytest.mark.asyncio
async def test_compute_solvency_solvent(session):
    """assets (channel + on-chain) >= liabilities (agent balances) → solvent."""
    from conduit_core.db.models import Agent

    session.add(Agent(id="ag1", name="a1", balance_sats=1000))
    session.add(Agent(id="ag2", name="a2", balance_sats=2000))
    await session.commit()

    lnd = _FakeLND(channel_local=5000, confirmed=1000)
    snap = await compute_solvency(session, lnd)

    assert snap.liabilities_sats == 3000
    assert snap.assets_sats == 6000
    assert snap.solvent is True
    assert snap.ratio == 2.0
    assert snap.agent_balance_sats == 3000
    assert snap.pending_outbound_sats == 0
    assert snap.error is None


@pytest.mark.asyncio
async def test_compute_solvency_insolvent(session):
    """liabilities exceed assets → not solvent, ratio < 1."""
    from conduit_core.db.models import Agent

    session.add(Agent(id="ag1", name="a1", balance_sats=10_000))
    await session.commit()

    lnd = _FakeLND(channel_local=1000, confirmed=500)
    snap = await compute_solvency(session, lnd)

    assert snap.liabilities_sats == 10_000
    assert snap.assets_sats == 1500
    assert snap.solvent is False
    assert snap.ratio is not None and snap.ratio < 1.0


@pytest.mark.asyncio
async def test_compute_solvency_pending_outbound_not_double_counted(session):
    """Pending outbound is REPORTED but NOT added to liabilities.

    The payment path debits balance_sats up-front (debit-before-pending), so a
    pending send's sats have already left Σ balance_sats — counting them again
    would double-count. Liabilities == Σ balance_sats only.
    """
    from conduit_core.db.models import Agent, Transaction

    # Realistic state: an agent funded with 5100 that has a 4100-sat send in
    # flight — the send was already debited, so balance_sats is the post-debit 1000.
    session.add(Agent(id="ag1", name="a1", balance_sats=1000))
    session.add(
        Transaction(
            id="tx1",
            agent_id="ag1",
            direction="send",
            amount_sats=4000,
            fee_sats=100,
            status="pending",
        )
    )
    # A settled send must NOT count toward liabilities either.
    session.add(
        Transaction(
            id="tx2",
            agent_id="ag1",
            direction="send",
            amount_sats=9999,
            fee_sats=50,
            status="settled",
        )
    )
    await session.commit()

    lnd = _FakeLND(channel_local=10_000, confirmed=0)
    snap = await compute_solvency(session, lnd)

    # pending_outbound is surfaced for observability...
    assert snap.pending_outbound_sats == 4100
    # ...but liabilities == Σ balance_sats only (NOT 1000 + 4100).
    assert snap.liabilities_sats == 1000
    assert snap.solvent is True


@pytest.mark.asyncio
async def test_compute_solvency_no_liabilities_is_solvent(session):
    """No agent balances + no pending → trivially solvent, ratio undefined."""
    lnd = _FakeLND(channel_local=0, confirmed=0)
    snap = await compute_solvency(session, lnd)
    assert snap.liabilities_sats == 0
    assert snap.solvent is True
    assert snap.ratio is None


@pytest.mark.asyncio
async def test_compute_solvency_lnd_error_is_conservative(session):
    """If LND balance can't be read, the snapshot reports not-solvent + error."""
    from conduit_core.db.models import Agent

    session.add(Agent(id="ag1", name="a1", balance_sats=1000))
    await session.commit()

    lnd = _FakeLND(channel_local=99_999, confirmed=0, raise_exc=True)
    snap = await compute_solvency(session, lnd)

    assert snap.error == "RuntimeError"
    assert snap.solvent is False
    assert snap.assets_sats == 0


# ---------- monitor lifecycle + publishing ----------

@pytest.mark.asyncio
async def test_monitor_check_publishes_snapshot(session):
    from conduit_core.db.database import SessionLocal
    from conduit_core.db.models import Agent

    async with SessionLocal() as s:
        s.add(Agent(id="ag1", name="a1", balance_sats=2000))
        await s.commit()

    lnd = _FakeLND(channel_local=5000, confirmed=0)
    monitor = SolvencyMonitor(lnd, SessionLocal, interval_seconds=300)
    snap = await monitor.check()

    assert latest_snapshot() is snap
    assert snap.liabilities_sats == 2000
    assert snap.solvent is True
    assert monitor.last_run_monotonic is not None


# ---------- enforcement ----------

def test_enforce_noop_when_disabled(monkeypatch):
    from conduit_core.config import get_settings

    # Default settings: enforce is False.
    s = get_settings()
    monkeypatch.setattr(s, "solvency_enforce", False, raising=False)
    # Publish an insolvent snapshot — must still be a no-op.
    from datetime import UTC, datetime

    from conduit_core.services.solvency import SolvencySnapshot, _store

    _store(
        SolvencySnapshot(
            liabilities_sats=10,
            assets_sats=1,
            agent_balance_sats=10,
            pending_outbound_sats=0,
            channel_local_sats=1,
            onchain_confirmed_sats=0,
            solvent=False,
            ratio=0.1,
            computed_at=datetime.now(UTC),
        )
    )
    enforce_solvent()  # no raise


def test_enforce_raises_when_enabled_and_insolvent(monkeypatch):
    from datetime import UTC, datetime

    from conduit_core.config import get_settings
    from conduit_core.services.solvency import SolvencySnapshot, _store

    s = get_settings()
    monkeypatch.setattr(s, "solvency_enforce", True, raising=False)
    _store(
        SolvencySnapshot(
            liabilities_sats=10,
            assets_sats=1,
            agent_balance_sats=10,
            pending_outbound_sats=0,
            channel_local_sats=1,
            onchain_confirmed_sats=0,
            solvent=False,
            ratio=0.1,
            computed_at=datetime.now(UTC),
        )
    )
    with pytest.raises(SolvencyError):
        enforce_solvent()


def test_enforce_passes_when_enabled_and_solvent(monkeypatch):
    from datetime import UTC, datetime

    from conduit_core.config import get_settings
    from conduit_core.services.solvency import SolvencySnapshot, _store

    s = get_settings()
    monkeypatch.setattr(s, "solvency_enforce", True, raising=False)
    _store(
        SolvencySnapshot(
            liabilities_sats=1,
            assets_sats=10,
            agent_balance_sats=1,
            pending_outbound_sats=0,
            channel_local_sats=10,
            onchain_confirmed_sats=0,
            solvent=True,
            ratio=10.0,
            computed_at=datetime.now(UTC),
        )
    )
    enforce_solvent()  # no raise


def test_enforce_noop_without_snapshot(monkeypatch):
    from conduit_core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "solvency_enforce", True, raising=False)
    # No snapshot published — must not raise (fail-open until we know).
    enforce_solvent()


# ---------- API surface ----------

@pytest.mark.asyncio
async def test_metrics_includes_solvency_fields(client):
    """/v1/metrics carries the solvency fields; defaults are sane with no snapshot."""
    r = await client.get("/v1/metrics")
    assert r.status_code == 200, r.text
    m = r.json()
    for key in ("liabilities_sats", "assets_sats", "solvency_ratio", "solvent"):
        assert key in m, f"{key} missing from MetricsOut"
    # No snapshot yet → defaults.
    assert m["solvent"] is True
    assert m["liabilities_sats"] == 0


@pytest.mark.asyncio
async def test_metrics_reflects_published_snapshot(client):
    from datetime import UTC, datetime

    from conduit_core.services.solvency import SolvencySnapshot, _store

    _store(
        SolvencySnapshot(
            liabilities_sats=3000,
            assets_sats=6000,
            agent_balance_sats=3000,
            pending_outbound_sats=0,
            channel_local_sats=6000,
            onchain_confirmed_sats=0,
            solvent=True,
            ratio=2.0,
            computed_at=datetime.now(UTC),
        )
    )
    r = await client.get("/v1/metrics")
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["liabilities_sats"] == 3000
    assert m["assets_sats"] == 6000
    assert m["solvency_ratio"] == 2.0
    assert m["solvent"] is True


@pytest.mark.asyncio
async def test_ready_includes_solvency_component_soft(client):
    """/v1/health/ready surfaces a solvency component but never 503s on insolvency."""
    from datetime import UTC, datetime

    from conduit_core.services.solvency import SolvencySnapshot, _store

    _store(
        SolvencySnapshot(
            liabilities_sats=10_000,
            assets_sats=100,
            agent_balance_sats=10_000,
            pending_outbound_sats=0,
            channel_local_sats=100,
            onchain_confirmed_sats=0,
            solvent=False,
            ratio=0.01,
            computed_at=datetime.now(UTC),
        )
    )
    r = await client.get("/v1/health/ready")
    # Soft: insolvency does NOT make readiness fail (DB is the only hard dep).
    assert r.status_code == 200, r.text
    body = r.json()
    assert "solvency" in body["components"]
    assert body["components"]["solvency"]["ok"] is False
    assert body["ok"] is True  # overall readiness unaffected


@pytest.mark.asyncio
async def test_ready_solvency_component_ok_without_snapshot(client):
    r = await client.get("/v1/health/ready")
    assert r.status_code == 200, r.text
    comp = r.json()["components"]["solvency"]
    assert comp["ok"] is True


# ---------- DB CHECK: non-negative balance ----------

@pytest.mark.asyncio
async def test_negative_balance_write_rejected(session):
    """A direct write driving balance_sats below zero must fail on commit."""
    import sqlalchemy.exc

    from conduit_core.db.models import Agent

    agent = Agent(id="neg1", name="neg-agent", balance_sats=100)
    session.add(agent)
    await session.commit()

    agent.balance_sats = -1
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        await session.commit()
    await session.rollback()


@pytest.mark.asyncio
async def test_zero_balance_write_allowed(session):
    """Zero is fine — only strictly-negative balances are rejected."""
    from conduit_core.db.models import Agent

    agent = Agent(id="zero1", name="zero-agent", balance_sats=0)
    session.add(agent)
    await session.commit()  # no raise
    assert agent.balance_sats == 0


# ---------- GET /metrics (Prometheus exposition) ----------

@pytest.mark.asyncio
async def test_prometheus_endpoint_returns_200(client):
    """GET /metrics (root path) returns 200 with Prometheus text when the client
    library is installed, or the graceful plaintext fallback otherwise."""
    from conduit_core.observability import _PROM_AVAILABLE

    r = await client.get("/metrics")
    assert r.status_code == 200, r.text
    body = r.text
    if _PROM_AVAILABLE:
        # Prometheus exposition is plaintext with HELP/TYPE comment lines.
        assert "text/plain" in r.headers.get("content-type", "")
        assert "# HELP" in body or "# TYPE" in body
        # One of our custom gauges should be registered.
        assert "conduit_" in body
    else:
        assert "prometheus_client not installed" in body


@pytest.mark.asyncio
async def test_prometheus_endpoint_no_auth_required(client):
    """The scrape endpoint is unauthenticated (ops endpoint)."""
    r = await client.get("/metrics", headers={"Authorization": ""})
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_prometheus_endpoint_reflects_solvency_snapshot(client):
    from datetime import UTC, datetime

    from conduit_core.observability import _PROM_AVAILABLE
    from conduit_core.services.solvency import SolvencySnapshot, _store

    if not _PROM_AVAILABLE:
        pytest.skip("prometheus_client not installed")

    _store(
        SolvencySnapshot(
            liabilities_sats=1234,
            assets_sats=5678,
            agent_balance_sats=1234,
            pending_outbound_sats=0,
            channel_local_sats=5678,
            onchain_confirmed_sats=0,
            solvent=True,
            ratio=4.6,
            computed_at=datetime.now(UTC),
        )
    )
    r = await client.get("/metrics")
    assert r.status_code == 200
    body = r.text
    assert "conduit_solvency_liabilities_sats 1234.0" in body
    assert "conduit_solvency_assets_sats 5678.0" in body
    assert "conduit_solvent 1.0" in body
