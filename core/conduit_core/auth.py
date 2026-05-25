from datetime import UTC, datetime

import bcrypt
import structlog
from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import get_session
from .db.models import APIKey
from .errors import AuthenticationError, PermissionError_
from .services.ids import api_key_id, api_key_secret

log = structlog.get_logger(__name__)

SCOPES = ("read", "write", "admin")
_SCOPE_RANK = {"read": 0, "write": 1, "admin": 2}


def hash_key(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_key(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode(), hashed.encode())
    except ValueError:
        return False


async def _extract_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationError("Missing Bearer token")
    return authorization.split(" ", 1)[1].strip()


async def _resolve_api_key(token: str, session: AsyncSession) -> APIKey:
    if not token.startswith(("ck_live_", "ck_test_")):
        raise AuthenticationError("Malformed API key")
    prefix = token[:8]
    # We can't query by raw key (hashed). Fetch active keys with same prefix and verify.
    result = await session.execute(
        select(APIKey).where(APIKey.revoked.is_(False), APIKey.prefix == prefix)
    )
    for row in result.scalars():
        if verify_key(token, row.key_hash):
            row.last_used_at = datetime.now(UTC)
            await session.commit()
            return row
    raise AuthenticationError("Invalid API key")


def require_scope(required: str):
    if required not in SCOPES:
        raise ValueError(f"unknown scope {required!r}")

    async def _dep(
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> APIKey:
        token = await _extract_bearer(authorization)
        key = await _resolve_api_key(token, session)
        if _SCOPE_RANK[key.scope] < _SCOPE_RANK[required]:
            raise PermissionError_(
                f"API key scope '{key.scope}' insufficient (requires '{required}')"
            )
        return key

    return _dep


async def ensure_bootstrap_key(session: AsyncSession) -> None:
    settings = get_settings()
    if not settings.bootstrap_api_key:
        return
    raw = settings.bootstrap_api_key
    if not raw.startswith(settings.api_key_prefix):
        log.warning(
            "bootstrap_key_prefix_mismatch",
            expected_prefix=settings.api_key_prefix,
            given_prefix=raw[:8],
        )
    result = await session.execute(select(APIKey).where(APIKey.label == "bootstrap"))
    existing = result.scalar_one_or_none()
    if existing:
        return
    key = APIKey(
        id=api_key_id(),
        label="bootstrap",
        key_hash=hash_key(raw),
        prefix=raw[:8],
        scope="admin",
    )
    session.add(key)
    await session.commit()
    log.info("bootstrap_api_key_created", key_id=key.id, scope=key.scope)


def mint_api_key(scope: str = "read") -> tuple[str, APIKey]:
    """Mint a fresh API key. Returns (raw_secret_shown_once, ORM row)."""
    settings = get_settings()
    raw = api_key_secret(settings.api_key_prefix)
    key = APIKey(
        id=api_key_id(),
        key_hash=hash_key(raw),
        prefix=raw[:8],
        scope=scope,
    )
    return raw, key
