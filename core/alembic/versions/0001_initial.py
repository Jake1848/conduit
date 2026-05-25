"""initial schema — agents, policies, transactions, api_keys, webhooks

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-25
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("label", sa.String(120), nullable=False, server_default=""),
        sa.Column("key_hash", sa.String(120), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False, server_default="read"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime, nullable=True),
        sa.Column("revoked", sa.Boolean, nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "agents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("pubkey", sa.String(80), nullable=True),
        sa.Column("lnd_label", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("api_key_id", sa.String(64), sa.ForeignKey("api_keys.id"), nullable=True),
        sa.Column("metadata_json", sa.Text, nullable=True),
        sa.Column("balance_sats", sa.BigInteger, nullable=False, server_default="0"),
    )

    op.create_table(
        "policies",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "agent_id",
            sa.String(64),
            sa.ForeignKey("agents.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("max_per_transaction", sa.BigInteger, nullable=True),
        sa.Column("max_per_hour", sa.BigInteger, nullable=True),
        sa.Column("max_per_day", sa.BigInteger, nullable=True),
        sa.Column("max_per_minute_count", sa.Integer, nullable=False, server_default="60"),
        sa.Column("allowlist", sa.Text, nullable=True),
        sa.Column("blocklist", sa.Text, nullable=True),
        sa.Column("require_memo", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "agent_id",
            sa.String(64),
            sa.ForeignKey("agents.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("amount_sats", sa.BigInteger, nullable=False),
        sa.Column("fee_sats", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("destination", sa.Text, nullable=True),
        sa.Column("payment_hash", sa.String(120), nullable=True, index=True),
        sa.Column("payment_preimage", sa.String(120), nullable=True),
        sa.Column("payment_request", sa.Text, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending", index=True),
        sa.Column("settled_at", sa.DateTime, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("memo", sa.Text, nullable=True),
        sa.Column("metadata_json", sa.Text, nullable=True),
        sa.Column("failure_reason", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
            index=True,
        ),
    )
    op.create_index("ix_tx_agent_created", "transactions", ["agent_id", "created_at"])
    op.create_index("ix_tx_agent_status", "transactions", ["agent_id", "status"])

    op.create_table(
        "webhooks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("events", sa.Text, nullable=False),
        sa.Column("secret", sa.String(120), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("webhooks")
    op.drop_index("ix_tx_agent_status", table_name="transactions")
    op.drop_index("ix_tx_agent_created", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("policies")
    op.drop_table("agents")
    op.drop_table("api_keys")
