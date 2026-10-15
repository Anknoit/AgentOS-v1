from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class Run(Base, TenantScopedMixin):
    """One execution of an agent — the durable control record for a managed job.

    A run is enqueued and executed off the request path (in-process in the dev-fallback, on an
    Arq worker in the full stack), so it survives a client disconnect and can be **resumed across
    a worker restart** from its LangGraph checkpoint (keyed by ``run_id``). The row is the source
    of truth for status and the rolled-up result; the step-by-step detail is in ``action_log``.

    ``agent_version_id`` pins the exact config that ran. Token/tool roll-ups are a convenience
    projection of the run's ``usage_event``s (which remain the billable source in Phase 3).
    """

    __tablename__ = "run"

    agent_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    agent_version_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)

    # queued | running | paused | completed | failed | killed
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False, index=True)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    trace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    # Roll-ups projected from this run's usage events (not the billable source of truth).
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    step_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
