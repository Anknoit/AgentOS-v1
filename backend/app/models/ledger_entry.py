from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class LedgerEntry(Base, TenantScopedMixin):
    """An immutable money movement — the append-only heart of the accounting core (Phase 3).

    One entry is written per rated event, attributed to its agent, run, and tenant. The row is
    **never updated or deleted**; balances are projections of the ledger (``wallet.balance_nanos``
    is the cache). Both ``cost_nanos`` (provider charge) and ``price_nanos`` (tenant pays) are
    recorded so margin is an accounted quantity, not a guess (Phase 4 relies on this).

    Exactly-once is enforced at the data layer. A rated-usage debit is unique on
    ``(tenant_id, usage_event_id)``, so a replayed usage event — same deterministic idempotency
    key, same ``usage_event`` row — can produce at most one ledger entry. A money-movement credit
    (Phase 4 ``topup``/``refund``/``adjustment``) is unique on ``(tenant_id, ref)`` where ``ref``
    is the gateway reference (``topup:<payment_id>``, ``refund:<refund_id>``), so the checkout
    callback and the webhook — which both report the same payment — credit the wallet at most once.
    A positive ``price_nanos`` is a debit (usage); a credit records the top-up amount in
    ``price_nanos`` with ``entry_type != "usage"`` and adds to the balance.
    """

    __tablename__ = "ledger_entry"
    __table_args__ = (
        UniqueConstraint("tenant_id", "usage_event_id", name="uq_ledger_usage_event"),
        UniqueConstraint("tenant_id", "ref", name="uq_ledger_ref"),
    )

    entry_type: Mapped[str] = mapped_column(String(16), default="usage", nullable=False)
    usage_event_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    # Gateway idempotency key for non-usage movements (topups/refunds); NULL for usage debits.
    ref: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)

    # denormalized from the usage event so spend queries don't re-join
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    cost_nanos: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    price_nanos: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)

    rate_card_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
