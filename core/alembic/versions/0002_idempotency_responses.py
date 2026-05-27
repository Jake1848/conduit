"""idempotency_responses table

Revision ID: 0002_idempotency
Revises: 0001_initial
Create Date: 2026-05-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_idempotency"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_responses",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "api_key_id",
            sa.String(64),
            sa.ForeignKey("api_keys.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_status", sa.Integer, nullable=False),
        sa.Column("response_body", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_idem_key_unique",
        "idempotency_responses",
        ["api_key_id", "key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_idem_key_unique", table_name="idempotency_responses")
    op.drop_table("idempotency_responses")
