"""settlement & payments — payments, invoices, wallet reservations, ledger credit idempotency

Phase 4 enters the payment path. It adds two tenant-scoped tables under the same
``FORCE ROW LEVEL SECURITY`` + ``app.current_tenant`` policy as the rest of the model, and
extends the Phase 3 ledger/wallet for money-in and reserve/hold:

* ``payment`` — one row per gateway (Razorpay) top-up order; the reconciliation anchor, unique on
  ``(tenant_id, order_id)`` so the checkout callback and the webhook credit the wallet once;
* ``invoice`` — a billing statement rolled from the ledger, unique on ``(tenant_id, number)``;
* ``wallet.reserved_nanos`` — funds held against in-flight work (available = balance - reserved);
* ``ledger_entry.ref`` + ``uq_ledger_ref`` — data-layer idempotency for non-usage credits
  (``topup:<payment_id>`` / ``refund:<refund_id>``), the money-in analogue of the usage-event key.

Revision ID: 0005_settlement
Revises: 0004_metering
Create Date: 2026-10-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_settlement"
down_revision = "0004_metering"
branch_labels = None
depends_on = None

RLS_TABLES = ["payment", "invoice"]


def _ts_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    # --- extend Phase 3 ledger/wallet ---
    op.add_column(
        "wallet",
        sa.Column("reserved_nanos", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column("ledger_entry", sa.Column("ref", sa.String(128), nullable=True))
    op.create_index("ix_ledger_entry_ref", "ledger_entry", ["ref"])
    op.create_unique_constraint("uq_ledger_ref", "ledger_entry", ["tenant_id", "ref"])

    op.create_table(
        "payment",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False, server_default="razorpay"),
        sa.Column("order_id", sa.String(64), nullable=False),
        sa.Column("payment_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="created"),
        sa.Column("amount_nanos", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("gateway_amount_minor", sa.Integer(), nullable=False),
        sa.Column("gateway_currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("method", sa.String(32), nullable=True),
        sa.Column("signature_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ledger_entry_id", sa.String(32), nullable=True),
        sa.Column("refunded_nanos", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("receipt", sa.String(64), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
        *_ts_columns(),
        sa.UniqueConstraint("tenant_id", "order_id", name="uq_payment_order"),
    )
    op.create_index("ix_payment_tenant_id", "payment", ["tenant_id"])
    op.create_index("ix_payment_order_id", "payment", ["order_id"])
    op.create_index("ix_payment_payment_id", "payment", ["payment_id"])
    op.create_index("ix_payment_trace_id", "payment", ["trace_id"])

    op.create_table(
        "invoice",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="issued"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_nanos", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("price_nanos", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("margin_nanos", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("line_items", sa.JSON(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        *_ts_columns(),
        sa.UniqueConstraint("tenant_id", "number", name="uq_invoice_number"),
    )
    op.create_index("ix_invoice_tenant_id", "invoice", ["tenant_id"])

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
    op.drop_table("invoice")
    op.drop_table("payment")
    op.drop_constraint("uq_ledger_ref", "ledger_entry", type_="unique")
    op.drop_index("ix_ledger_entry_ref", table_name="ledger_entry")
    op.drop_column("ledger_entry", "ref")
    op.drop_column("wallet", "reserved_nanos")
