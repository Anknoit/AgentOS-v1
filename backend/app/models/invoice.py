from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class Invoice(Base, TenantScopedMixin):
    """One billing statement per tenant across the whole fleet (Phase 4).

    Line items are **rolled from the append-only ledger** for the period (grouped by agent and
    event type), never recomputed from provider responses, so the statement is exactly what was
    accounted. Both the provider ``cost`` and the tenant ``price`` are totalled; ``margin_nanos``
    is ``price - cost`` — the platform's accounted margin, not a guess. The invoice is a statement
    of usage in the prepaid model (payment is the wallet balance); ``status`` moves draft → issued
    → paid | void. ``number`` is a per-tenant human sequence (``INV-0001``).
    """

    __tablename__ = "invoice"
    __table_args__ = (UniqueConstraint("tenant_id", "number", name="uq_invoice_number"),)

    number: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="issued", nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)

    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    event_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_nanos: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    price_nanos: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    margin_nanos: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    line_items: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
