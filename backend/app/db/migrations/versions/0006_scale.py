"""scale & reliability — durable event log + consumer offsets

Phase 5 makes the metering stream durable and replayable. It adds two tenant-scoped tables under
the same ``FORCE ROW LEVEL SECURITY`` + ``app.current_tenant`` policy as the rest of the model:

* ``event_log`` — the append-only, offset-ordered usage stream (the dev-fallback analogue of a
  Kafka topic). Its primary key is a DB-native autoincrement ``offset`` so the stream is orderable
  and gap-resumable; replay re-reads a range and the idempotent pipeline absorbs it.
* ``consumer_offset`` — a named consumer's committed position per tenant (the idempotent
  checkpoint), unique on ``(tenant_id, consumer)``.

No existing table changes — Phase 5 is purely additive to the accounting core.

Revision ID: 0006_scale
Revises: 0005_settlement
Create Date: 2026-10-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_scale"
down_revision = "0005_settlement"
branch_labels = None
depends_on = None

RLS_TABLES = ["event_log", "consumer_offset"]


def _ts_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "event_log",
        # DB-native monotonic offset (BIGSERIAL on Postgres, INTEGER PK autoincrement on SQLite).
        sa.Column(
            "offset",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_event_log_tenant_id", "event_log", ["tenant_id"])
    op.create_index("ix_event_log_subject", "event_log", ["subject"])
    op.create_index("ix_event_log_trace_id", "event_log", ["trace_id"])
    # The hot replay/lag query filters by tenant and scans forward by offset.
    op.create_index("ix_event_log_tenant_offset", "event_log", ["tenant_id", "offset"])

    op.create_table(
        "consumer_offset",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("consumer", sa.String(64), nullable=False),
        sa.Column("committed_offset", sa.BigInteger(), nullable=False, server_default="0"),
        *_ts_columns(),
        sa.UniqueConstraint("tenant_id", "consumer", name="uq_consumer_offset"),
    )
    op.create_index("ix_consumer_offset_tenant_id", "consumer_offset", ["tenant_id"])

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
    op.drop_table("consumer_offset")
    op.drop_table("event_log")
