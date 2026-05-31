"""timezone-aware datetime columns (TIMESTAMPTZ on Postgres)

The models declared every datetime column as naive `DateTime`
(Postgres TIMESTAMP WITHOUT TIME ZONE), but the application writes and
compares timezone-AWARE values (datetime.now(UTC)). asyncpg strictly
rejects aware↔naive mixing, so on Postgres every authenticated request
(auth updates api_keys.last_used_at), the reconciler sweep, and the
policy-window queries failed with a DataError. SQLite is tz-lax, which is
why the test suite never caught it.

This converts the affected columns to TIMESTAMPTZ on Postgres, treating
the existing naive values as UTC. On SQLite there is no tz-aware column
type, so this migration is a no-op there (SQLite stores the offset in the
value, and `DateTime(timezone=True)` reflects identically to `DateTime`).

Revision ID: 0003_tz_aware
Revises: 0002_idempotency
Create Date: 2026-05-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_tz_aware"
down_revision: str | None = "0002_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column) pairs that hold UTC timestamps.
_COLUMNS = [
    ("api_keys", "created_at"),
    ("api_keys", "last_used_at"),
    ("agents", "created_at"),
    ("policies", "created_at"),
    ("policies", "updated_at"),
    ("transactions", "settled_at"),
    ("transactions", "created_at"),
    ("webhooks", "created_at"),
    ("idempotency_responses", "created_at"),
]


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # SQLite has no tz-aware column type — nothing to alter.
    for table, col in _COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {col} TYPE TIMESTAMPTZ "
            f"USING {col} AT TIME ZONE 'UTC'"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, col in _COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {col} TYPE TIMESTAMP "
            f"USING {col} AT TIME ZONE 'UTC'"
        )
