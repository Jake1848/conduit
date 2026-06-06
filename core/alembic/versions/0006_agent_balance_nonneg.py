"""add CHECK (balance_sats >= 0) to agents

The agent ledger maintains a virtual per-agent balance. The money path already
refuses to debit below zero under a row lock, but a negative balance is such a
serious invariant violation (double-spend / refund bug) that we make it a
database-level CHECK so it cannot happen even via a direct write or a future
code path that forgets the application guard.

Works on both SQLite and Postgres. On SQLite, ALTER TABLE cannot add a CHECK
constraint, so op.create_check_constraint runs inside a batch (table copy);
on Postgres it issues a plain ALTER TABLE ... ADD CONSTRAINT.

Revision ID: 0006_agent_balance_nonneg
Revises: 0005_platform_fee
Create Date: 2026-06-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_agent_balance_nonneg"
down_revision: str | None = "0005_platform_fee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_agents_balance_nonneg"
_TABLE = "agents"
_CONDITION = "balance_sats >= 0"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite has no ALTER TABLE ADD CONSTRAINT; batch_alter_table rebuilds the
        # table with the constraint baked in.
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.create_check_constraint(_CONSTRAINT, _CONDITION)
    else:
        op.create_check_constraint(_CONSTRAINT, _TABLE, _CONDITION)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.drop_constraint(_CONSTRAINT, type_="check")
    else:
        op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
