import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

# Ensure in-memory DB + mock LND BEFORE the app imports settings.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("LND_MOCK", "true")
os.environ.setdefault("CONDUIT_NETWORK", "testnet")
os.environ.setdefault("BOOTSTRAP_API_KEY", "ck_test_root_for_tests")
os.environ.setdefault("API_SECRET_KEY", "test-secret-key")

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
    from conduit_core.main import app  # import after env is set

    # Ensure bootstrap key exists for the tests.
    from conduit_core.auth import ensure_bootstrap_key
    from conduit_core.db.database import SessionLocal

    async with SessionLocal() as s:
        await ensure_bootstrap_key(s)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.headers["Authorization"] = "Bearer ck_test_root_for_tests"
        yield c


@pytest_asyncio.fixture
async def session():
    from conduit_core.db.database import SessionLocal

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as s:
        yield s
