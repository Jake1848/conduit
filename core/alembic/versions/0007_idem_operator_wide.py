"""scope idempotency keys operator-wide (unique on key alone)

Previously the unique index was (api_key_id, key), so the same Idempotency-Key
sent under two of the operator's API keys did NOT dedupe — a cross-key retry of
the same payment could double-charge. This migration makes the key operator-wide:
unique on `key` alone. `api_key_id` stays as an audit column.

Before creating the new unique index we must collapse any rows that share a key
(keep the most recent), or the unique index creation would fail.

Revision ID: 0007_idem_operator_wide
Revises: 0006_agent_balance_nonneg
Create Date: 2026-06-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_idem_operator_wide"
down_revision: str | None = "0006_agent_balance_nonneg"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_idem_key_unique"
_TABLE = "idempotency_responses"


def upgrade() -> None:
    # Collapse duplicate keys (different api_key_id, same key) keeping the newest
    # row, so the operator-wide unique index can be built. Ties on created_at are
    # broken by id. Safe: idempotency rows are a transient cache (pruned by TTL).
    op.execute(
        f"""
        DELETE FROM {_TABLE} a
        USING {_TABLE} b
        WHERE a.key = b.key
          AND (a.created_at < b.created_at
               OR (a.created_at = b.created_at AND a.id < b.id))
        """
    )
    op.drop_index(_INDEX, table_name=_TABLE)
    op.create_index(_INDEX, _TABLE, ["key"], unique=True)


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
    op.create_index(_INDEX, _TABLE, ["api_key_id", "key"], unique=True)
