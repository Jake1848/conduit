"""index idempotency_responses.created_at for the retention prune

The IdempotencyPruner deletes rows past the retention window
(DELETE ... WHERE created_at < cutoff). Without an index that is a full
table scan every prune cycle; this adds a btree on created_at so the
prune stays cheap as the table grows.

Revision ID: 0004_idem_created_at
Revises: 0003_tz_aware
Create Date: 2026-06-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_idem_created_at"
down_revision: str | None = "0003_tz_aware"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_idem_created_at"
_TABLE = "idempotency_responses"


def upgrade() -> None:
    op.create_index(_INDEX, _TABLE, ["created_at"])


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
