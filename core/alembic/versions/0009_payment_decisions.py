"""payment_decisions — durable, inspectable record of every payment decision

Records EVERY payment attempt — settled, failed, AND policy/balance/destination
rejected — with the MARGIN to each threshold (how close it came to each limit,
captured even when allowed), the applied policy snapshot+hash (so a later policy
edit can't make a past decision un-reconstructable), and which key/caller
initiated it. Unlike `transactions`, this table also records rejected attempts —
the thing an operator most needs to inspect later. Never stores secrets.

Revision ID: 0009_payment_decisions
Revises: 0008_treasury_withdrawals
Create Date: 2026-06-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_payment_decisions"
down_revision: str | None = "0008_treasury_withdrawals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "payment_decisions"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("agent_id", sa.String(64), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=True),
        sa.Column("requested_sats", sa.BigInteger(), nullable=False),
        sa.Column("destination", sa.Text(), nullable=True),
        sa.Column("destination_kind", sa.String(16), nullable=True),
        sa.Column("allowlist_status", sa.String(24), nullable=True),
        sa.Column("api_key_id", sa.String(64), nullable=True),
        sa.Column("caller_tag", sa.String(80), nullable=True),
        sa.Column("balance_at_decision_sats", sa.BigInteger(), nullable=True),
        sa.Column("thresholds_json", sa.Text(), nullable=True),
        sa.Column("binding_rule", sa.String(24), nullable=True),
        sa.Column("min_margin_pct", sa.Float(), nullable=True),
        sa.Column("policy_snapshot_json", sa.Text(), nullable=True),
        sa.Column("policy_hash", sa.String(64), nullable=True),
        sa.Column("tx_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_payment_decisions_agent_id", _TABLE, ["agent_id"])
    op.create_index("ix_payment_decisions_outcome", _TABLE, ["outcome"])
    op.create_index("ix_payment_decisions_tx_id", _TABLE, ["tx_id"])
    op.create_index("ix_payment_decisions_created_at", _TABLE, ["created_at"])
    op.create_index("ix_decisions_agent_created", _TABLE, ["agent_id", "created_at"])
    op.create_index("ix_decisions_outcome_created", _TABLE, ["outcome", "created_at"])
    op.create_index("ix_decisions_min_margin", _TABLE, ["min_margin_pct"])


def downgrade() -> None:
    op.drop_index("ix_decisions_min_margin", table_name=_TABLE)
    op.drop_index("ix_decisions_outcome_created", table_name=_TABLE)
    op.drop_index("ix_decisions_agent_created", table_name=_TABLE)
    op.drop_index("ix_payment_decisions_created_at", table_name=_TABLE)
    op.drop_index("ix_payment_decisions_tx_id", table_name=_TABLE)
    op.drop_index("ix_payment_decisions_outcome", table_name=_TABLE)
    op.drop_index("ix_payment_decisions_agent_id", table_name=_TABLE)
    op.drop_table(_TABLE)
