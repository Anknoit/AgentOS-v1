from __future__ import annotations

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class Alert(Base, TenantScopedMixin):
    """A spend/anomaly notice raised by the metering path (Phase 3, build task 6).

    Kinds: ``budget_soft`` / ``budget_hard`` (a cap was neared or hit), ``spend_spike`` (one event
    cost far above the run's recent average), ``runaway_loop`` (a run billed far more steps than
    expected). Alerts are append-only observations attributable to a run/agent; the client lists
    them in the spend view. Detection runs inline in the metering transaction so an alert is never
    lost to a dropped async message.
    """

    __tablename__ = "alert"

    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), default="warning", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    context: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
