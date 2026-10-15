from __future__ import annotations

from sqlalchemy import JSON, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class ActionLog(Base, TenantScopedMixin):
    """Append-only audit trail of everything a run did.

    Every step, model call, and tool call is appended here with the run's ``trace_id`` — a
    black-box run becomes a complete, inspectable record (a core differentiator). Rows are never
    updated or deleted; ``seq`` is monotonic per run and unique, so appends are idempotent on
    replay (a resumed node that re-emits the same ``seq`` is a no-op — see ``runtime.actions``).

    ``usage_event_id`` cross-links a billable step to the ``usage_event`` it captured, so cost is
    attributable down to the individual action.
    """

    __tablename__ = "action_log"
    __table_args__ = (UniqueConstraint("tenant_id", "run_id", "seq", name="uq_action_run_seq"),)

    run_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)

    # run_started | node | model_call | tool_call | usage | run_paused | run_resumed
    # | run_completed | run_failed | run_killed
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    usage_event_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
