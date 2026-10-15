from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class UsageEvent(Base, TenantScopedMixin):
    """One billable unit of work — the heart of the moat.

    Carries an **idempotency key**: rating and ledger writes (Phase 3) dedupe on
    ``(tenant_id, idempotency_key)`` so a retried model call or a replayed event never
    double-bills. In Phase 0 we only *capture* events (``rated=False``); nothing prices them yet.

    ``agent_id`` / ``run_id`` are plain nullable string refs so metering can be captured before
    the Phase 1 agent/run tables exist.
    """

    __tablename__ = "usage_event"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_usage_tenant_idem"),
    )

    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)

    # what happened
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)  # model_call | tool_call
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # quantities
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # e.g. 1 tool call
    unit: Mapped[str] = mapped_column(String(32), default="tokens", nullable=False)

    # correlation / lifecycle
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    rated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # Phase 3
