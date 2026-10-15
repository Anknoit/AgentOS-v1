"""initial schema + row-level security

Creates the Phase 0 tables and switches on **row-level security** for tenant-scoped data
tables (the non-negotiable isolation invariant). Identity tables (tenant, user, api_key) are
intentionally *not* RLS-protected: the auth path must resolve an API key to a tenant before any
tenant context exists (ADR-0004), so their access is guarded in application code instead.

``FORCE ROW LEVEL SECURITY`` is required because the app connects as the table owner, which
would otherwise bypass RLS. Policies compare ``tenant_id`` against the transaction-local GUC
``app.current_tenant`` set by ``db.session.tenant_session``.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

# Tenant-scoped data tables that get RLS now. Grows each phase (agent, run, action_log,
# ledger_entry, wallet, ...).
RLS_TABLES = ["usage_event"]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "tenant",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_tenant_slug", "tenant", ["slug"], unique=True)

    op.create_table(
        "user",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="owner"),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),
    )
    op.create_index("ix_user_tenant_id", "user", ["tenant_id"])

    op.create_table(
        "api_key",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=True),
        sa.Column("name", sa.String(128), nullable=False, server_default="default"),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(128), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_api_key_tenant_id", "api_key", ["tenant_id"])
    op.create_index("ix_api_key_prefix", "api_key", ["prefix"])
    op.create_index("ix_api_key_key_hash", "api_key", ["key_hash"], unique=True)

    op.create_table(
        "usage_event",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=True),
        sa.Column("agent_id", sa.String(32), nullable=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("unit", sa.String(32), nullable=False, server_default="tokens"),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("rated", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_usage_tenant_idem"),
    )
    op.create_index("ix_usage_event_tenant_id", "usage_event", ["tenant_id"])
    op.create_index("ix_usage_event_run_id", "usage_event", ["run_id"])
    op.create_index("ix_usage_event_agent_id", "usage_event", ["agent_id"])
    op.create_index("ix_usage_event_trace_id", "usage_event", ["trace_id"])

    # --- Row-level security on tenant-scoped data tables ---
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
    op.drop_table("usage_event")
    op.drop_table("api_key")
    op.drop_table("user")
    op.drop_table("tenant")
