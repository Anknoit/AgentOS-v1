"""Schemas for the scale & reliability ops surface (Phase 5)."""

from __future__ import annotations

from pydantic import BaseModel


class StreamHealthOut(BaseModel):
    """Metering ingestion health for the tenant's durable event stream."""

    tenant_id: str
    head_offset: int
    event_count: int
    committed_offset: int
    lag: int


class ReplayRequest(BaseModel):
    from_offset: int | None = None  # default: resume from the committed offset
    commit: bool = True  # False => dry run, don't advance the consumer offset


class ReplayResultOut(BaseModel):
    """The outcome of a stream replay — the exactly-once / recovery proof."""

    tenant_id: str
    from_offset: int
    to_offset: int
    replayed: int
    repaired: int
    new_ledger_entries: int
    balance_delta_nanos: int
    exactly_once: bool


class SchedulerStatsOut(BaseModel):
    """Fair-scheduler capacity and this tenant's share of it."""

    max_concurrency: int
    per_tenant_concurrency: int
    running_total: int
    tenant_running: int
    tenant_waiting: int


class ProviderHealthOut(BaseModel):
    """Model-router state: which providers are healthy vs. circuit-open."""

    failover_enabled: bool
    candidates: list[str]
    providers: dict[str, dict]
