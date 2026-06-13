"""treasury_withdrawals — durable record of operator on-chain withdrawals

A withdrawal is written `pending` before the irreversible LND broadcast and
updated to `broadcast` (+txid) after, so a crash in the broadcast window leaves
a reconcilable record instead of silently-spent funds. Doubles as the operator's
BTC-transfer history.

Revision ID: 0008_treasury_withdrawals
Revises: 0007_idem_operator_wide
Create Date: 2026-06-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_treasury_withdrawals"
down_revision: str | None = "0007_idem_operator_wide"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "treasury_withdrawals"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("amount_sats", sa.BigInteger(), nullable=False),
        sa.Column("address", sa.String(120), nullable=False),
        sa.Column("sat_per_vbyte", sa.Integer(), nullable=True),
        sa.Column("fee_reserve_sats", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("txid", sa.String(80), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=True),
        sa.Column("assets_sats_after", sa.BigInteger(), nullable=True),
        sa.Column("liabilities_sats_after", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_twd_created_at", _TABLE, ["created_at"])
    # Idempotency store for the withdraw endpoint. NULLs are distinct, so keyless
    # withdrawals don't collide.
    op.create_index("ix_twd_idem_key", _TABLE, ["idempotency_key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_twd_idem_key", table_name=_TABLE)
    op.drop_index("ix_twd_created_at", table_name=_TABLE)
    op.drop_table(_TABLE)
