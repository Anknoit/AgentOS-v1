"""Scale & reliability ops endpoints (Phase 5).

A thin, tenant-scoped window onto the reliability machinery: metering-ingestion health (how far the
durable stream's consumer is lagging), a safe **replay** of the tenant's usage stream (idempotent —
re-rates nothing already rated, repairs any gap, and reports the exactly-once result), the fair
scheduler's capacity and this tenant's share of it, and the model router's provider health. These
are the levers an operator reaches for during a load test or an incident — the data behind the
exit criteria (exactly-once under replay, no starvation, provider failover).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.config.settings import get_settings
from app.core.auth import CurrentTenant
from app.metering import stream
from app.runtime.router import get_health
from app.runtime.scheduler import get_scheduler
from app.schemas.ops import (
    ProviderHealthOut,
    ReplayRequest,
    ReplayResultOut,
    SchedulerStatsOut,
    StreamHealthOut,
)

router = APIRouter()


@router.get("/stream", response_model=StreamHealthOut)
async def stream_health(tenant: CurrentTenant) -> StreamHealthOut:
    """Durable metering-stream health: log head, event count, consumer offset, and lag."""
    h = await stream.stream_depth(tenant.tenant_id)
    return StreamHealthOut(
        tenant_id=h.tenant_id,
        head_offset=h.head_offset,
        event_count=h.event_count,
        committed_offset=h.committed_offset,
        lag=h.lag,
    )


@router.post("/replay", response_model=ReplayResultOut)
async def replay_stream(
    tenant: CurrentTenant, payload: ReplayRequest | None = None
) -> ReplayResultOut:
    """Replay the tenant's usage stream through the idempotent pipeline.

    Safe to run any time: already-rated events are no-ops, so a healthy stream yields zero new
    ledger entries and zero balance change (``exactly_once=True``); a captured-but-unrated gap is
    repaired exactly once. This is both the exactly-once proof and the recovery tool.
    """
    payload = payload or ReplayRequest()
    r = await stream.replay_usage(
        tenant.tenant_id, from_offset=payload.from_offset, commit=payload.commit
    )
    return ReplayResultOut(
        tenant_id=r.tenant_id,
        from_offset=r.from_offset,
        to_offset=r.to_offset,
        replayed=r.replayed,
        repaired=r.repaired,
        new_ledger_entries=r.new_ledger_entries,
        balance_delta_nanos=r.balance_delta,
        exactly_once=r.exactly_once,
    )


@router.get("/scheduler", response_model=SchedulerStatsOut)
async def scheduler_stats(tenant: CurrentTenant) -> SchedulerStatsOut:
    """Fair-scheduler capacity and this tenant's running/waiting share (fairness + backpressure)."""
    sched = get_scheduler()
    stats = sched.stats()
    return SchedulerStatsOut(
        max_concurrency=stats["max_concurrency"],
        per_tenant_concurrency=stats["per_tenant_concurrency"],
        running_total=stats["running_total"],
        tenant_running=sched.running(tenant.tenant_id),
        tenant_waiting=sched.waiting(tenant.tenant_id),
    )


@router.get("/providers", response_model=ProviderHealthOut)
async def provider_health(tenant: CurrentTenant) -> ProviderHealthOut:
    """Model-router provider health: candidates and which circuits are open (failover state)."""
    settings = get_settings()
    return ProviderHealthOut(
        failover_enabled=settings.provider_failover,
        candidates=list(settings.provider_candidates),
        providers=get_health(settings).snapshot(),
    )
