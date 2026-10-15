from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class RateCard(Base, TenantScopedMixin):
    """Versioned pricing — per-model token prices, per-tool/connector fees, platform markup.

    Rating is the telecom pattern: a card is **versioned with an effective date** and never edited
    in place. A price change writes a new card with a later ``effective_at``; historical events
    stay priced by the card that was active when they occurred, so re-rating a replayed event is
    stable. The active card for a tenant is the one with ``is_active`` and the latest
    ``effective_at <= now``.

    Prices live in JSON (``model_prices`` keyed by model → ``{"input","output"}`` per-1M-token
    strings; ``tool_fees`` / ``connector_fees`` keyed by name → per-call strings) so the shape is
    portable and queryable without a row per line item. ``markup_pct`` turns cost into tenant price
    — 0 in the Phase 3 BYO default, raised in Phase 4 where margin becomes an accounted quantity.
    """

    __tablename__ = "rate_card"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", "version", name="uq_rate_card_version"),
    )

    name: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    model_prices: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    tool_fees: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    connector_fees: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    markup_pct: Mapped[str] = mapped_column(String(16), default="0", nullable=False)
