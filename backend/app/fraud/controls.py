"""Velocity limits + holds — the fraud/abuse gate on billable work (Phase 6, build task 3).

Three controls, all converging on one primitive — the **tenant hold**:

* **Velocity limits** — a sliding-window counter per ``(tenant, kind)`` caps how fast a tenant can
  start runs or confirm top-ups. Tripping it raises :class:`VelocityError` (429) *and* places a
  hold, so the abuse stops immediately instead of only throttling.
* **Anomaly-driven holds** — ``evaluate_anomaly_holds`` promotes recent critical anomalies (a
  runaway loop) into a hold. Run it from the operator scan endpoint / a cron, off the request hot
  path, so it never contends with the metering transaction.
* **Prepaid-abuse protection** — the top-up velocity limit plus the hold check in ``confirm_topup``
  stop top-up churn / stolen-card cycling.

The sliding-window counters are **in-process** (the hermetic default); at scale the seam is a
shared store (Redis) keyed the same way. Holds are durable rows (``tenant_hold``), so a hold
survives a restart even though the counters don't.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config.settings import get_settings
from app.core.errors import TenantHeldError, VelocityError
from app.core.logging import get_logger
from app.db.session import tenant_session
from app.metering.anomaly import raise_alert
from app.models.alert import Alert
from app.models.tenant_hold import TenantHold

log = get_logger(__name__)

# (tenant_id, kind) -> monotonic timestamps of recent events (newest at the right).
_events: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def _reset_counters() -> None:
    """Clear the in-process velocity windows (used by tests)."""
    _events.clear()


def record_event(tenant_id: str, kind: str, *, window_s: float, now: float | None = None) -> int:
    """Record one event and return the count within the trailing ``window_s`` seconds."""
    now = now if now is not None else time.monotonic()
    dq = _events[(tenant_id, kind)]
    dq.append(now)
    cutoff = now - window_s
    while dq and dq[0] < cutoff:
        dq.popleft()
    return len(dq)


async def active_hold(tenant_id: str) -> TenantHold | None:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                select(TenantHold).where(
                    TenantHold.tenant_id == tenant_id, TenantHold.active.is_(True)
                )
            )
        ).scalars().first()


async def assert_not_held(tenant_id: str) -> None:
    """Raise :class:`TenantHeldError` if the tenant has an active hold (no-op if fraud is off)."""
    if not get_settings().fraud_enabled:
        return
    hold = await active_hold(tenant_id)
    if hold is not None:
        raise TenantHeldError(f"tenant is on hold: {hold.reason}")


async def place_hold(
    tenant_id: str, *, kind: str, reason: str, context: dict | None = None
) -> TenantHold:
    """Place a hold (idempotent: an existing active hold of the same kind is returned as-is)."""
    async with tenant_session(tenant_id) as session:
        existing = (
            await session.execute(
                select(TenantHold).where(
                    TenantHold.tenant_id == tenant_id,
                    TenantHold.active.is_(True),
                    TenantHold.kind == kind,
                )
            )
        ).scalars().first()
        if existing is not None:
            return existing
        hold = TenantHold(
            tenant_id=tenant_id, kind=kind, reason=reason, active=True, context=context or {}
        )
        session.add(hold)
        await session.flush()
        await raise_alert(
            session,
            tenant_id=tenant_id,
            kind="fraud_hold",
            severity="critical",
            message=f"tenant placed on hold ({kind}): {reason}",
            context={"hold_id": hold.id, "kind": kind, **(context or {})},
            dedupe_per_run=False,
        )
        await session.refresh(hold)
        log.warning("fraud.hold_placed", tenant_id=tenant_id, kind=kind, reason=reason)
        return hold


async def release_hold(
    tenant_id: str, hold_id: str, *, released_by: str = "operator"
) -> TenantHold:
    from app.core.errors import NotFoundError

    async with tenant_session(tenant_id) as session:
        hold = (
            await session.execute(
                select(TenantHold).where(
                    TenantHold.tenant_id == tenant_id, TenantHold.id == hold_id
                )
            )
        ).scalar_one_or_none()
        if hold is None:
            raise NotFoundError(f"hold '{hold_id}' not found")
        hold.active = False
        hold.released_at = datetime.now(timezone.utc)
        hold.released_by = released_by
        await session.flush()
        await session.refresh(hold)
        return hold


async def list_holds(tenant_id: str, *, active_only: bool = False) -> list[TenantHold]:
    async with tenant_session(tenant_id) as session:
        stmt = (
            select(TenantHold)
            .where(TenantHold.tenant_id == tenant_id)
            .order_by(TenantHold.created_at.desc())
        )
        if active_only:
            stmt = stmt.where(TenantHold.active.is_(True))
        return list((await session.execute(stmt)).scalars().all())


async def check_velocity(
    tenant_id: str, kind: str, *, limit: int, window_s: float
) -> None:
    """Record an event; if the window count exceeds ``limit``, place a hold and raise (429)."""
    if not get_settings().fraud_enabled:
        return
    count = record_event(tenant_id, kind, window_s=window_s)
    if count > limit:
        await place_hold(
            tenant_id,
            kind="velocity",
            reason=f"{kind} velocity limit exceeded ({count} > {limit} / {window_s:.0f}s)",
            context={"kind": kind, "count": count, "limit": limit, "window_s": window_s},
        )
        raise VelocityError(
            f"{kind} rate limit exceeded ({count} in {window_s:.0f}s, limit {limit})"
        )


async def guard_run(tenant_id: str) -> None:
    """The run-trigger gate: refuse if held, then apply the run velocity limit. Raises on abuse."""
    settings = get_settings()
    if not settings.fraud_enabled:
        return
    await assert_not_held(tenant_id)
    await check_velocity(
        tenant_id,
        "run",
        limit=settings.fraud_run_velocity_limit,
        window_s=settings.fraud_run_velocity_window_s,
    )


async def guard_topup(tenant_id: str) -> None:
    """The top-up gate (prepaid-abuse protection): refuse if held, then apply top-up velocity."""
    settings = get_settings()
    if not settings.fraud_enabled:
        return
    await assert_not_held(tenant_id)
    await check_velocity(
        tenant_id,
        "topup",
        limit=settings.fraud_topup_velocity_limit,
        window_s=settings.fraud_topup_velocity_window_s,
    )


async def evaluate_anomaly_holds(
    tenant_id: str, *, now: datetime | None = None
) -> TenantHold | None:
    """Promote recent critical anomalies into a hold (operator scan / cron — off the hot path).

    Looks for runaway-loop/critical alerts within ``fraud_anomaly_window_s`` and, if any are
    present and no hold is active, places an anomaly hold. Returns the hold it placed (or the
    existing active one), else ``None``.
    """
    settings = get_settings()
    if not (settings.fraud_enabled and settings.fraud_hold_on_anomaly):
        return None
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=settings.fraud_anomaly_window_s)
    async with tenant_session(tenant_id) as session:
        alerts = list(
            (
                await session.execute(
                    select(Alert).where(
                        Alert.tenant_id == tenant_id,
                        Alert.kind == "runaway_loop",
                        Alert.severity == "critical",
                        Alert.created_at >= cutoff,
                    )
                )
            ).scalars().all()
        )
    if not alerts:
        return None
    return await place_hold(
        tenant_id,
        kind="anomaly",
        reason=f"{len(alerts)} runaway-loop anomaly(ies) in the last "
        f"{settings.fraud_anomaly_window_s:.0f}s",
        context={"anomaly_count": len(alerts), "run_ids": [a.run_id for a in alerts if a.run_id]},
    )
