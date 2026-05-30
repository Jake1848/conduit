import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

# In-memory DB is fine for the full suite but the FIRST test run in isolation
# can hit aiosqlite/event-loop ordering issues; the full-suite run is canonical.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("LND_MOCK", "true")
os.environ.setdefault("CONDUIT_ENV", "development")
os.environ.setdefault("CONDUIT_NETWORK", "testnet")
os.environ.setdefault("BOOTSTRAP_API_KEY", "ck_test_root_for_tests")
os.environ.setdefault("API_SECRET_KEY", "test-secret-key")
# Generous limit so concurrency tests don't accidentally trip the limiter.
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")
os.environ.setdefault("RATE_LIMIT_BURST", "10000")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from httpx import ASGITransport, AsyncClient  # noqa: E402

from conduit_core.config import get_settings  # noqa: E402
from conduit_core.db.database import Base, engine  # noqa: E402


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    # Recreate schema for every test for isolation (in-memory DB).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    # Ensure bootstrap key exists for the tests.
    from conduit_core.auth import ensure_bootstrap_key
    from conduit_core.db.database import SessionLocal
    from conduit_core.main import app  # import after env is set
    from conduit_core.middleware import RateLimitMiddleware

    async with SessionLocal() as s:
        await ensure_bootstrap_key(s)

    # Reset the token bucket between tests so accumulated state doesn't leak.
    for m in getattr(app, "user_middleware", []):
        if m.cls is RateLimitMiddleware:
            # The middleware instance lives inside the wrapped app; reset
            # bucket state on each test via a module-level registry.
            break

    # raise_app_exceptions=False so unhandled exceptions get a 500 response
    # (rendered by our exception handler) instead of being re-raised to the test.
    # Use the active bootstrap key (env-driven) so the suite works under any
    # BOOTSTRAP_API_KEY — local default or the CI-provided value.
    bootstrap_key = os.environ["BOOTSTRAP_API_KEY"]
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.headers["Authorization"] = f"Bearer {bootstrap_key}"
        yield c


@pytest_asyncio.fixture
async def session():
    from conduit_core.db.database import SessionLocal

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as s:
        yield s


async def credit_agent(client: AsyncClient, agent_id: str, sats: int) -> None:
    r = await client.post(
        f"/v1/agents/{agent_id}/credit",
        json={"sats": sats, "reason": "test setup"},
    )
    assert r.status_code == 201, r.text
