from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class TenantHold(Base, TenantScopedMixin):
    """A fraud/abuse hold blocking a tenant's billable work until an operator releases it (Phase 6).

    A hold is placed when a tenant trips a velocity limit (too many runs/top-ups in a window), when
    an anomaly fires (a runaway loop), or manually by an operator. While an ``active`` hold exists,
    the credit/run path refuses new billable actions (``TenantHeldError``) — a per-tenant circuit
    breaker. Releasing sets ``active=False`` and stamps ``released_at``; the row is kept as an
    audit record, never deleted.
    """

    __tablename__ = "tenant_hold"

    # velocity | anomaly | manual
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    context: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
