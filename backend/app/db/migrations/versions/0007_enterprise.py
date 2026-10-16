"""enterprise & hardening — audit log, fraud holds, marketplace, RBAC/residency columns

Phase 6 adds the trust-and-expansion surface. All additive — the accounting core is untouched.

* ``audit_log`` — tenant-scoped, append-only control-plane audit trail (SOC 2). Under the same
  ``FORCE ROW LEVEL SECURITY`` + ``app.current_tenant`` policy as the rest of the model.
* ``tenant_hold`` — tenant-scoped fraud/abuse holds that gate billable work. RLS as above.
* ``marketplace_listing`` — a **cross-tenant public catalogue** of shareable agent templates and
  connector configs. Intentionally **not** under RLS (the one table outside tenant isolation);
  accessed only via ``system_session``. Secrets are never stored here.
* ``api_key.role`` — RBAC role carried by a key (scoped keys).
* ``tenant.region`` — data-residency label.

Revision ID: 0007_enterprise
Revises: 0006_scale
Create Date: 2026-10-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_enterprise"
down_revision = "0006_scale"
branch_labels = None
depends_on = None

RLS_TABLES = ["audit_log", "tenant_hold"]


def _ts_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    # --- RBAC / residency columns on existing tables (additive, with safe server defaults) ---
    op.add_column(
        "api_key",
        sa.Column("role", sa.String(32), nullable=False, server_default="owner"),
    )
    op.add_column(
        "tenant",
        sa.Column("region", sa.String(32), nullable=False, server_default="global"),
    )

    # --- audit_log (tenant-scoped, RLS) ---
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False, server_default="system"),
        sa.Column("actor_type", sa.String(16), nullable=False, server_default="system"),
        sa.Column("actor_role", sa.String(32), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=True),
        sa.Column("resource_id", sa.String(64), nullable=True),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=True),
        *_ts_columns(),
    )
    op.create_index("ix_audit_log_tenant_id", "audit_log", ["tenant_id"])
    op.create_index("ix_audit_log_actor_id", "audit_log", ["actor_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_trace_id", "audit_log", ["trace_id"])

    # --- tenant_hold (tenant-scoped, RLS) ---
    op.create_table(
        "tenant_hold",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by", sa.String(64), nullable=True),
        *_ts_columns(),
    )
    op.create_index("ix_tenant_hold_tenant_id", "tenant_hold", ["tenant_id"])
    op.create_index("ix_tenant_hold_active", "tenant_hold", ["active"])

    # --- marketplace_listing (PUBLIC catalogue — no RLS by design) ---
    op.create_table(
        "marketplace_listing",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("publisher_tenant_id", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("installs", sa.Integer(), nullable=False, server_default="0"),
        *_ts_columns(),
        sa.UniqueConstraint("slug", name="uq_marketplace_slug"),
    )
    op.create_index("ix_marketplace_publisher", "marketplace_listing", ["publisher_tenant_id"])
    op.create_index("ix_marketplace_kind", "marketplace_listing", ["kind"])

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
    op.drop_table("marketplace_listing")
    op.drop_table("tenant_hold")
    op.drop_table("audit_log")
    op.drop_column("tenant", "region")
    op.drop_column("api_key", "role")
