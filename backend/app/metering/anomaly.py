"""Simple, inline anomaly detection on the metering path (Phase 3, build task 6).

Two cheap checks run in the same transaction that rates an event — so an alert is durable, never
lost to a dropped async message:

* **runaway loop** — a run that bills far more steps than any sane agent loop should (a prompt-
  injection or a stuck graph burning tokens);
* **spend spike** — a single event priced far above the run's running average (a surprise large
  model call).

Thresholds are deliberately high so ordinary runs (a handful of billable steps) never trip them;
tuning/ML lives in a later phase. Alerts are written through :func:`raise_alert`, deduped per
(run, kind) so a runaway run raises one alert, not hundreds.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.metering.money import format_usd
from app.models.alert import Alert
from app.models.ledger_entry import LedgerEntry
from app.models.usage_event import UsageEvent

log = get_logger(__name__)

RUNAWAY_STEP_THRESHOLD = 50  # billable steps in one run
SPIKE_FACTOR = 10  # an event this many× the run average
SPIKE_MIN_PRIOR = 3  # need a few prior events before "average" means anything


async def raise_alert(
    session: AsyncSession,
    *,
    tenant_id: str,
    kind: str,
    severity: str,
    message: str,
    run_id: str | None = None,
    agent_id: str | None = None,
    context: dict | None = None,
    dedupe_per_run: bool = True,
) -> Alert | None:
    """Append one alert, optionally at most once per (run, kind). Returns the row or None."""
    if dedupe_per_run and run_id is not None:
        existing = (
            await session.execute(
                select(Alert.id).where(
                    Alert.tenant_id == tenant_id, Alert.run_id == run_id, Alert.kind == kind
                )
            )
        ).first()
        if existing is not None:
            return None
    alert = Alert(
        tenant_id=tenant_id,
        kind=kind,
        severity=severity,
        message=message,
        run_id=run_id,
        agent_id=agent_id,
        context=context or {},
    )
    session.add(alert)
    await session.flush()
    log.warning("alert.raised", kind=kind, severity=severity, run_id=run_id, message=message)
    return alert


async def check_event(
    session: AsyncSession,
    *,
    tenant_id: str,
    run_id: str | None,
    agent_id: str | None,
    price_nanos: int,
) -> None:
    """Run the inline checks for the event just rated into ``session``."""
    if run_id is None:
        return

    # Runaway loop: too many billable usage events on one run.
    step_count = (
        await session.execute(
            select(func.count())
            .select_from(UsageEvent)
            .where(UsageEvent.tenant_id == tenant_id, UsageEvent.run_id == run_id)
        )
    ).scalar_one()
    if step_count >= RUNAWAY_STEP_THRESHOLD:
        await raise_alert(
            session,
            tenant_id=tenant_id,
            kind="runaway_loop",
            severity="critical",
            message=f"run {run_id} billed {step_count} steps (>= {RUNAWAY_STEP_THRESHOLD})",
            run_id=run_id,
            agent_id=agent_id,
            context={"step_count": step_count, "threshold": RUNAWAY_STEP_THRESHOLD},
        )

    # Spend spike: this event priced far above the run's average so far.
    agg = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(LedgerEntry.price_nanos), 0)).where(
                LedgerEntry.tenant_id == tenant_id, LedgerEntry.run_id == run_id
            )
        )
    ).one()
    count, total = int(agg[0]), int(agg[1])
    prior_count = count - 1  # this event's entry is already written
    prior_total = total - price_nanos
    if prior_count >= SPIKE_MIN_PRIOR and prior_total > 0:
        avg = prior_total / prior_count
        if price_nanos > SPIKE_FACTOR * avg:
            await raise_alert(
                session,
                tenant_id=tenant_id,
                kind="spend_spike",
                severity="warning",
                message=(
                    f"event cost {format_usd(price_nanos)} is >{SPIKE_FACTOR}× the run average "
                    f"{format_usd(int(avg))}"
                ),
                run_id=run_id,
                agent_id=agent_id,
                context={"price_nanos": price_nanos, "run_avg_nanos": int(avg)},
                dedupe_per_run=False,
            )
