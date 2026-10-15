"""Persistence helpers for runs and the append-only action log.

Each helper runs in its own short tenant-scoped transaction so a run's progress is durable
step-by-step (a crash mid-run leaves a consistent prefix, and the checkpoint resumes the rest).
``append_action`` is idempotent on ``(run_id, seq)``: a node that re-executes after a resume
re-appends the same row as a no-op, mirroring the exactly-once contract of ``capture_usage``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.session import tenant_session
from app.models.action_log import ActionLog
from app.models.run import Run

log = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_run(
    *,
    tenant_id: str,
    run_id: str,
    task: str,
    agent_id: str | None,
    agent_version_id: str | None,
    trace_id: str | None,
    status: str = "queued",
) -> Run:
    async with tenant_session(tenant_id) as session:
        run = Run(
            id=run_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            task=task,
            trace_id=trace_id,
            status=status,
        )
        session.add(run)
    return run


async def get_run(tenant_id: str, run_id: str) -> Run | None:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                select(Run).where(Run.tenant_id == tenant_id, Run.id == run_id)
            )
        ).scalar_one_or_none()


async def set_run_status(
    tenant_id: str, run_id: str, status: str, *, error: str | None = None
) -> None:
    async with tenant_session(tenant_id) as session:
        run = (
            await session.execute(
                select(Run).where(Run.tenant_id == tenant_id, Run.id == run_id)
            )
        ).scalar_one_or_none()
        if run is None:
            return
        run.status = status
        if status == "running" and run.started_at is None:
            run.started_at = _now()
        if status in ("completed", "failed", "killed"):
            run.ended_at = _now()
        if error is not None:
            run.error = error


async def finalize_run(
    tenant_id: str,
    run_id: str,
    *,
    status: str,
    output: str | None = None,
    error: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    tool_calls: int = 0,
    step_count: int = 0,
) -> None:
    async with tenant_session(tenant_id) as session:
        run = (
            await session.execute(
                select(Run).where(Run.tenant_id == tenant_id, Run.id == run_id)
            )
        ).scalar_one_or_none()
        if run is None:
            return
        run.status = status
        run.output = output
        run.error = error
        run.input_tokens = input_tokens
        run.output_tokens = output_tokens
        run.total_tokens = input_tokens + output_tokens
        run.tool_calls = tool_calls
        run.step_count = step_count
        run.ended_at = _now()


async def append_action(
    *,
    tenant_id: str,
    run_id: str,
    seq: int,
    type: str,
    name: str | None = None,
    content: dict | None = None,
    usage_event_id: str | None = None,
    trace_id: str | None = None,
) -> ActionLog:
    """Append one audit row, idempotent on ``(run_id, seq)`` (safe to replay on resume)."""
    async with tenant_session(tenant_id) as session:
        existing = (
            await session.execute(
                select(ActionLog).where(
                    ActionLog.tenant_id == tenant_id,
                    ActionLog.run_id == run_id,
                    ActionLog.seq == seq,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        row = ActionLog(
            tenant_id=tenant_id,
            run_id=run_id,
            seq=seq,
            type=type,
            name=name,
            content=content or {},
            usage_event_id=usage_event_id,
            trace_id=trace_id,
        )
        session.add(row)
    return row


async def list_actions(tenant_id: str, run_id: str, *, limit: int = 1000) -> list[ActionLog]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                select(ActionLog)
                .where(ActionLog.tenant_id == tenant_id, ActionLog.run_id == run_id)
                .order_by(ActionLog.seq.asc())
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)
