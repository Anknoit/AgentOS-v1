"""metering, rating & budgets — rate card, append-only ledger, wallet, budgets, alerts

Phase 3 stands up the accounting core. Five tenant-scoped tables, all under the same
``FORCE ROW LEVEL SECURITY`` + ``app.current_tenant`` policy as the rest of the data model:

* ``rate_card`` — versioned pricing (per-model/token, per-tool/connector, markup), effective-dated;
* ``ledger_entry`` — immutable money movements, one per rated usage event, unique on
  ``(tenant_id, usage_event_id)`` so a replayed event posts at most once (exactly-once rating);
* ``wallet`` — cached balance projection, one per tenant;
* ``budget`` — spend caps for online credit control;
* ``alert`` — spend/anomaly notices.

Money is stored as integer nanodollars (``BigInteger``) — exact on Postgres and SQLite alike.

Revision ID: 0004_metering
Revises: 0003_connectors
Create Date: 2026-10-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_metering"
down_revision = "0003_connectors"
branch_labels = None
depends_on = None

RLS_TABLES = ["rate_card", "ledger_entry", "wallet", "budget", "alert"]


def _ts_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "rate_card",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(64), nullable=False, server_default="default"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("model_prices", sa.JSON(), nullable=False),
        sa.Column("tool_fees", sa.JSON(), nullable=False),
        sa.Column("connector_fees", sa.JSON(), nullable=False),
        sa.Column("markup_pct", sa.String(16), nullable=False, server_default="0"),
        *_ts_columns(),
        sa.UniqueConstraint("tenant_id", "name", "version", name="uq_rate_card_version"),
    )
    op.create_index("ix_rate_card_tenant_id", "rate_card", ["tenant_id"])

    op.create_table(
        "ledger_entry",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("entry_type", sa.String(16), nullable=False, server_default="usage"),
        sa.Column("usage_event_id", sa.String(32), nullable=True),
        sa.Column("run_id", sa.String(32), nullable=True),
        sa.Column("agent_id", sa.String(32), nullable=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("cost_nanos", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("price_nanos", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("rate_card_id", sa.String(32), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
        *_ts_columns(),
        sa.UniqueConstraint("tenant_id", "usage_event_id", name="uq_ledger_usage_event"),
    )
    op.create_index("ix_ledger_entry_tenant_id", "ledger_entry", ["tenant_id"])
    op.create_index("ix_ledger_entry_usage_event_id", "ledger_entry", ["usage_event_id"])
    op.create_index("ix_ledger_entry_run_id", "ledger_entry", ["run_id"])
    op.create_index("ix_ledger_entry_agent_id", "ledger_entry", ["agent_id"])
    op.create_index("ix_ledger_entry_trace_id", "ledger_entry", ["trace_id"])

    op.create_table(
        "wallet",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("balance_nanos", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("enforce_balance", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_ts_columns(),
        sa.UniqueConstraint("tenant_id", name="uq_wallet_tenant"),
    )
    op.create_index("ix_wallet_tenant_id", "wallet", ["tenant_id"])

    op.create_table(
        "budget",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(64), nullable=False, server_default="budget"),
        sa.Column("scope", sa.String(16), nullable=False, server_default="tenant"),
        sa.Column("scope_id", sa.String(32), nullable=True),
        sa.Column("period", sa.String(16), nullable=False, server_default="total"),
        sa.Column("limit_nanos", sa.BigInteger(), nullable=False),
        sa.Column("enforcement", sa.String(8), nullable=False, server_default="hard"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_ts_columns(),
    )
    op.create_index("ix_budget_tenant_id", "budget", ["tenant_id"])
    op.create_index("ix_budget_scope_id", "budget", ["scope_id"])

    op.create_table(
        "alert",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="warning"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=True),
        sa.Column("agent_id", sa.String(32), nullable=True),
        sa.Column("context", sa.JSON(), nullable=False),
        *_ts_columns(),
    )
    op.create_index("ix_alert_tenant_id", "alert", ["tenant_id"])
    op.create_index("ix_alert_kind", "alert", ["kind"])
    op.create_index("ix_alert_run_id", "alert", ["run_id"])
    op.create_index("ix_alert_agent_id", "alert", ["agent_id"])

    for table in RLS_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON "{table}"
            USING (tenant_id = current_setting('app.current_tenant', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant', true))
            """
        )


def downgrade() -> None:
    for table in RLS_TABLES:
        op.execute(f'DROP POLICY IF EXISTS {table}_tenant_isolation ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.drop_table("alert")
    op.drop_table("budget")
    op.drop_table("wallet")
    op.drop_table("ledger_entry")
    op.drop_table("rate_card")
