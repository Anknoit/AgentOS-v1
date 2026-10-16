"""Run service — turn an agent + task into a managed, streamed, resumable run."""

from __future__ import annotations

import uuid

from app.config.settings import Settings, get_settings
from app.core.errors import ConflictError, NotFoundError
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.runtime import store
from app.runtime.kernel import RunContext, execute_run
from app.runtime.manager import get_run_manager
from app.services import agents as agents_service


def build_context(
    *,
    tenant_id: str,
    run_id: str,
    agent_id: str | None,
    version: AgentVersion,
    trace_id: str | None,
    settings: Settings,
) -> RunContext:
    return RunContext(
        tenant_id=tenant_id,
        run_id=run_id,
        agent_id=agent_id,
        agent_version_id=version.id,
        model=version.model,
        system_prompt=version.system_prompt,
        tools=list(version.tools or []),
        trace_id=trace_id,
        settings=settings,
        connector_bindings=dict(version.connector_bindings or {}),
        guardrails=dict(version.guardrails or {}),
    )


async def trigger_run(
    *,
    tenant_id: str,
    agent: Agent,
    version: AgentVersion,
    task: str,
    trace_id: str | None,
    settings: Settings | None = None,
) -> tuple[str, bool]:
    """Create a run and dispatch it. Returns ``(run_id, enqueued)``."""
    settings = settings or get_settings()
    # Fraud/abuse gate (Phase 6): refuse if the tenant is on hold, apply the run velocity limit.
    from app.fraud.controls import guard_run

    await guard_run(tenant_id)
    run_id = uuid.uuid4().hex
    await store.create_run(
        tenant_id=tenant_id,
        run_id=run_id,
        task=task,
        agent_id=agent.id,
        agent_version_id=version.id,
        trace_id=trace_id,
        status="queued",
    )

    if settings.use_inprocess_runtime:
        ctx = build_context(
            tenant_id=tenant_id,
            run_id=run_id,
            agent_id=agent.id,
            version=version,
            trace_id=trace_id,
            settings=settings,
        )
        get_run_manager().start(
            run_id, lambda: execute_run(ctx, task=task), tenant_id=tenant_id
        )
        return run_id, False

    from app.runtime.queue import enqueue_agent_run

    await enqueue_agent_run(
        tenant_id=tenant_id,
        run_id=run_id,
        agent_id=agent.id,
        agent_version_id=version.id,
        task=task,
        trace_id=trace_id,
    )
    return run_id, True


async def resume_run(
    *, tenant_id: str, run_id: str, settings: Settings | None = None
) -> str:
    """Resume a paused/queued run from its last checkpoint (survives a worker restart)."""
    settings = settings or get_settings()
    run = await store.get_run(tenant_id, run_id)
    if run is None:
        raise NotFoundError(f"run '{run_id}' not found")
    if run.status in ("completed", "killed"):
        raise ConflictError(f"run '{run_id}' is {run.status} and cannot be resumed")
    if run.agent_version_id is None:
        raise ConflictError(f"run '{run_id}' has no pinned agent version")

    version = await agents_service.get_version(tenant_id, run.agent_version_id)
    ctx = build_context(
        tenant_id=tenant_id,
        run_id=run_id,
        agent_id=run.agent_id,
        version=version,
        trace_id=run.trace_id,
        settings=settings,
    )
    get_run_manager().start(
        run_id, lambda: execute_run(ctx, task=run.task, resume=True), tenant_id=tenant_id
    )
    return run_id
