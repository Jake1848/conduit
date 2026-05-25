from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from ..config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
# connect_args carries dialect-specific bits — used to keep SQLite usable
# from multiple asyncio tasks via the aiosqlite shim.
_connect_args: dict = {}
if _settings.database_url.startswith("sqlite"):
    _connect_args["check_same_thread"] = False
engine = create_async_engine(
    _settings.database_url, future=True, echo=False, connect_args=_connect_args
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


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
