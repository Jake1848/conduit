"""add transactions.platform_fee_sats (operator platform-fee revenue)

The self-hosted fee model charges a per-payment platform fee (the operator's
revenue), recorded per transaction so it can be aggregated by /v1/fees and
refunded correctly on failure. Added NOT NULL with a server default of 0 so
existing rows backfill cleanly; the model keeps the same server_default so
`alembic check` stays clean on both SQLite and Postgres.

Revision ID: 0005_platform_fee
Revises: 0004_idem_created_at
Create Date: 2026-06-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_platform_fee"
down_revision: str | None = "0004_idem_created_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column(
            "platform_fee_sats",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("transactions", "platform_fee_sats")
