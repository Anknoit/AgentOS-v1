"""agent runtime tables + row-level security

Phase 1 adds the agent runtime's data model: ``agent`` and immutable ``agent_version`` (config is
data, versioned), ``run`` (the durable control record for a managed job), and the append-only
``action_log``. All four are tenant-scoped data tables, so they get the same row-level security
treatment as ``usage_event`` — ``FORCE ROW LEVEL SECURITY`` plus a policy comparing ``tenant_id``
to the transaction-local GUC ``app.current_tenant`` set by ``db.session.tenant_session``.

Revision ID: 0002_agent_runtime
Revises: 0001_initial
Create Date: 2026-10-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_agent_runtime"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

RLS_TABLES = ["agent", "agent_version", "run", "action_log"]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "agent",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("template", sa.String(64), nullable=True),
        sa.Column("role", sa.String(128), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("current_version_id", sa.String(32), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_agent_tenant_slug"),
    )
    op.create_index("ix_agent_tenant_id", "agent", ["tenant_id"])
    op.create_index("ix_agent_slug", "agent", ["slug"])

    op.create_table(
        "agent_version",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("agent_id", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("tools", sa.JSON(), nullable=False),
        sa.Column("guardrails", sa.JSON(), nullable=False),
        sa.Column("knowledge", sa.JSON(), nullable=False),
        sa.Column("connector_bindings", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "agent_id", "version", name="uq_agent_version"),
    )
    op.create_index("ix_agent_version_tenant_id", "agent_version", ["tenant_id"])
    op.create_index("ix_agent_version_agent_id", "agent_version", ["agent_id"])

    op.create_table(
        "run",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("agent_id", sa.String(32), nullable=True),
        sa.Column("agent_version_id", sa.String(32), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("step_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_run_tenant_id", "run", ["tenant_id"])
    op.create_index("ix_run_agent_id", "run", ["agent_id"])
    op.create_index("ix_run_agent_version_id", "run", ["agent_version_id"])
    op.create_index("ix_run_status", "run", ["status"])
    op.create_index("ix_run_trace_id", "run", ["trace_id"])

    op.create_table(
        "action_log",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("usage_event_id", sa.String(32), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "run_id", "seq", name="uq_action_run_seq"),
    )
    op.create_index("ix_action_log_tenant_id", "action_log", ["tenant_id"])
    op.create_index("ix_action_log_run_id", "action_log", ["run_id"])
    op.create_index("ix_action_log_trace_id", "action_log", ["trace_id"])

    # --- Row-level security on the new tenant-scoped data tables ---
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
    op.drop_table("action_log")
    op.drop_table("run")
    op.drop_table("agent_version")
    op.drop_table("agent")
