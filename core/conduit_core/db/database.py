import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from ..config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
_is_sqlite = _settings.database_url.startswith("sqlite")
# connect_args carries dialect-specific bits — used to keep SQLite usable
# from multiple asyncio tasks via the aiosqlite shim.
_connect_args: dict = {}
_engine_kwargs: dict = {"future": True, "echo": False, "connect_args": _connect_args}

if _is_sqlite:
    _connect_args["check_same_thread"] = False
    # Wait (rather than immediately erroring with "database is locked") when a
    # concurrent writer holds the file — paired with WAL below this lets the
    # multi-session money path behave like a real RDBMS on dev/test SQLite.
    _connect_args["timeout"] = 30
elif "pytest" in sys.modules and _settings.database_url.startswith("postgresql"):
    # TEST-ONLY: under pytest, pytest-asyncio runs each test on a fresh event loop,
    # but a pooled asyncpg connection is bound to the loop that created it — reusing
    # it on the next test's loop raises `RuntimeError: got Future attached to a
    # different loop` (which is why the Postgres CI job was red). NullPool opens a
    # fresh connection per operation, so nothing is cached across loops. Production
    # keeps normal pooling; this branch never triggers outside the test runner.
    _engine_kwargs["poolclass"] = NullPool
else:
    # Postgres in production: validate each pooled connection before use so a
    # recycled/stale socket (LB idle-timeout, failover) is transparently replaced
    # instead of surfacing as a query error on the money path. Recycle well under
    # typical infra idle timeouts.
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["pool_size"] = _settings.db_pool_size
    _engine_kwargs["max_overflow"] = _settings.db_max_overflow
    _engine_kwargs["pool_recycle"] = 1800

engine = create_async_engine(_settings.database_url, **_engine_kwargs)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

if _is_sqlite:
    # WAL gives concurrent readers + a single writer with committed-data visibility
    # across connections — the isolation behaviour the idempotency reservation and
    # the payment ledger rely on. `:memory:` can't do this (it collapses to one
    # connection), which is why dev/test use a file URL.
    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - infra wiring
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()


async def init_db() -> None:
    """Bring the schema up to date.

    In dev/test we use SQLAlchemy `create_all` for zero-config startup. In
    production we expect Alembic migrations to have been applied OUT-OF-BAND
    (the operator runs `alembic upgrade head` as part of deploy). If you
    forget, the app will start but writes will fail loudly the first time
    a missing column is referenced — better than create_all silently
    diverging from the migration history.
    """
    from . import models  # noqa: F401  ensure models are registered

    settings = get_settings()
    if settings.is_production:
        # Don't auto-create; that would defeat the purpose of versioned migrations.
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
