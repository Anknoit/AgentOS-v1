"""connector credential vault + row-level security

Phase 2 adds the ``credential`` table: per-tenant connector secrets stored **encrypted at rest**
(the application encrypts with a tenant-derived key before insert — see ADR-0008). The row is
tenant-scoped data, so it gets the same ``FORCE ROW LEVEL SECURITY`` + ``app.current_tenant``
policy treatment as the other tenant tables. Encryption and RLS are defence in depth: RLS keeps a
tenant from reading another's rows, and per-tenant encryption keeps a leaked row unreadable.

Revision ID: 0003_connectors
Revises: 0002_agent_runtime
Create Date: 2026-10-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_connectors"
down_revision = "0002_agent_runtime"
branch_labels = None
depends_on = None

RLS_TABLES = ["credential"]


def upgrade() -> None:
    op.create_table(
        "credential",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("connector_key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(64), nullable=False, server_default="default"),
        sa.Column("auth_type", sa.String(16), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("provider_meta", sa.JSON(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "connector_key", "name", name="uq_credential_tenant_key"),
    )
    op.create_index("ix_credential_tenant_id", "credential", ["tenant_id"])
    op.create_index("ix_credential_connector_key", "credential", ["connector_key"])

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
    op.drop_table("credential")
