"""Job-queue seam (ADR-0001: Arq / Redis).

Runs execute **off the request path** as managed jobs so they survive client disconnect,
deploy, and worker restart. This module is the single point of coupling to the engine — a later
swap to Temporal is contained here.

Phase 0 keeps it thin:

* with ``REDIS_URL`` unset, the API runs the agent loop **in-process** (no worker needed to
  boot — ADR-0006), so this seam is dormant;
* with Redis configured, ``enqueue_run`` pushes a job and the Arq worker executes
  ``execute_run_job``. The W3C traceparent is carried in the payload so the worker's spans join
  the same trace as the request that enqueued it.

Streaming run events back from a separate worker process (Redis pub/sub) is Phase 1 work; in
Phase 0 the worker runs the loop to completion and logs it.
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.config.settings import Settings, get_settings
from app.core.context import TenantContext, set_tenant, set_trace_id
from app.core.logging import get_logger
from app.core.tracing import attach_traceparent, inject_traceparent
from app.runtime.agent import run_agent_loop

log = get_logger(__name__)

# Number of per-tenant queue partitions on the Arq path. A tenant always maps to the same
# partition (so its runs stay ordered), but tenants are spread across partitions so a flood from
# one lands on one queue and workers on the others keep serving everyone else — the distributed
# analogue of the in-process FairScheduler's per-tenant cap (Phase 5, build task 1).
QUEUE_PARTITIONS = 8


def partition_for(tenant_id: str) -> str:
    """Stable queue name for a tenant: ``arq:runs:<n>``."""
    h = int(hashlib.sha256(tenant_id.encode()).hexdigest(), 16)
    return f"arq:runs:{h % QUEUE_PARTITIONS}"


def build_run_payload(*, tenant_id: str, task: str, run_id: str, trace_id: str | None) -> dict:
    return {
        "tenant_id": tenant_id,
        "task": task,
        "run_id": run_id,
        "trace_id": trace_id,
        "traceparent": inject_traceparent(),
    }


async def execute_run_job(ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Arq task: execute a run to completion on a worker. Returns a small result summary."""
    settings: Settings = ctx.get("settings") or get_settings()
    set_trace_id(payload.get("trace_id"))
    set_tenant(TenantContext(tenant_id=payload["tenant_id"]))

    events: list[dict] = []
    with attach_traceparent(payload.get("traceparent")):
        async for event in run_agent_loop(
            tenant_id=payload["tenant_id"],
            task=payload["task"],
            settings=settings,
            run_id=payload.get("run_id"),
        ):
            events.append(event)

    done = next((e for e in reversed(events) if e["type"] in ("done", "error")), {})
    log.info("worker.run_complete", run_id=payload.get("run_id"), events=len(events))
    return {"run_id": payload.get("run_id"), "result": done, "event_count": len(events)}


async def enqueue_run(*, tenant_id: str, task: str, run_id: str, trace_id: str | None) -> str:
    """Enqueue a run onto Arq. Requires Redis; raises if not configured."""
    settings = get_settings()
    if settings.redis_url is None:
        raise RuntimeError("enqueue_run requires AGENTOS_REDIS_URL")
    from arq import create_pool
    from arq.connections import RedisSettings

    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        job = await pool.enqueue_job(
            "execute_run_job",
            build_run_payload(tenant_id=tenant_id, task=task, run_id=run_id, trace_id=trace_id),
        )
        return job.job_id if job else run_id
    finally:
        await pool.close()


# ---- Phase 1: durable agent runs on a worker ----
async def execute_agent_run_job(ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Arq task: execute an agent run (pinned to its agent_version) to completion on a worker.

    The run survives a worker restart: on restart a supervisor re-enqueues unfinished runs and
    the kernel resumes from the LangGraph checkpoint (``resume=True``).
    """
    settings: Settings = ctx.get("settings") or get_settings()
    set_trace_id(payload.get("trace_id"))
    set_tenant(TenantContext(tenant_id=payload["tenant_id"]))

    from app.runtime.kernel import execute_run
    from app.runtime.store import get_run
    from app.services.agents import get_version
    from app.services.runs import build_context

    version = await get_version(payload["tenant_id"], payload["agent_version_id"])
    run = await get_run(payload["tenant_id"], payload["run_id"])
    resume = run is not None and run.status in ("paused", "running")
    rc = build_context(
        tenant_id=payload["tenant_id"],
        run_id=payload["run_id"],
        agent_id=payload.get("agent_id"),
        version=version,
        trace_id=payload.get("trace_id"),
        settings=settings,
    )

    count = 0
    with attach_traceparent(payload.get("traceparent")):
        async for _event in execute_run(rc, task=payload["task"], resume=resume):
            count += 1
    log.info("worker.agent_run_complete", run_id=payload["run_id"], events=count)
    return {"run_id": payload["run_id"], "event_count": count}


async def enqueue_agent_run(
    *,
    tenant_id: str,
    run_id: str,
    agent_id: str | None,
    agent_version_id: str,
    task: str,
    trace_id: str | None,
) -> str:
    """Enqueue an agent run onto Arq. Requires Redis; raises if not configured."""
    settings = get_settings()
    if settings.redis_url is None:
        raise RuntimeError("enqueue_agent_run requires AGENTOS_REDIS_URL")
    from arq import create_pool
    from arq.connections import RedisSettings

    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        job = await pool.enqueue_job(
            "execute_agent_run_job",
            {
                "tenant_id": tenant_id,
                "run_id": run_id,
                "agent_id": agent_id,
                "agent_version_id": agent_version_id,
                "task": task,
                "trace_id": trace_id,
                "traceparent": inject_traceparent(),
            },
            _queue_name=partition_for(tenant_id),  # per-tenant partition (fair scheduling)
        )
        return job.job_id if job else run_id
    finally:
        await pool.close()


# ---- Arq worker configuration (used by `arq app.runtime.queue.WorkerSettings`) ----
async def _startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    from app.bootstrap import init_runtime

    init_runtime(settings)
    ctx["settings"] = settings
    log.info("worker.startup", redis=settings.redis_url)


class WorkerSettings:
    functions = [execute_run_job, execute_agent_run_job]
    on_startup = _startup
    # A worker serves one partition when AGENTOS_WORKER_QUEUE is set; else Arq's default queue.
    queue_name = get_settings().worker_queue or "arq:queue"

    @staticmethod
    def redis_settings():
        from arq.connections import RedisSettings

        settings = get_settings()
        return RedisSettings.from_dsn(settings.redis_url or "redis://localhost:6379/0")
