"""Data-retention enforcement (Phase 6, build task 1).

Deletes **operational** rows older than ``AGENTOS_DATA_RETENTION_DAYS`` — the run history, the
agent action log, the durable event log, and alerts. These are telemetry; they age out.

The **money ledger is never purged**: ``ledger_entry``, ``invoice``, ``payment``, and the
``usage_event`` rows they roll up are immutable financial record, kept for reconciliation and
dispute resolution regardless of the retention horizon. The ``audit_log`` is likewise retained
(a security review expects a complete control-plane trail). ``0`` days means retain everything.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.config.settings import get_settings
from app.core.logging import get_logger
from app.db.session import system_session, tenant_session
from app.models.action_log import ActionLog
from app.models.alert import Alert
from app.models.event_log import EventLog
from app.models.run import Run
from app.models.tenant import Tenant

log = get_logger(__name__)

# Operational tables that age out. (Order doesn't matter — no FKs between them.)
_PURGEABLE = (Run, ActionLog, EventLog, Alert)


async def purge_tenant(tenant_id: str, *, now: datetime | None = None) -> dict[str, int]:
    """Purge one tenant's expired operational rows. Returns ``{table: deleted}`` (empty if off)."""
    settings = get_settings()
    if settings.data_retention_days <= 0:
        return {}
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=settings.data_retention_days)
    deleted: dict[str, int] = {}
    async with tenant_session(tenant_id) as session:
        for model in _PURGEABLE:
            result = await session.execute(
                delete(model).where(
                    model.tenant_id == tenant_id, model.created_at < cutoff
                )
            )
            deleted[model.__tablename__] = result.rowcount or 0
    log.info("retention.purged", tenant_id=tenant_id, cutoff=cutoff.isoformat(), **deleted)
    return deleted


async def purge_all(*, now: datetime | None = None) -> dict[str, int]:
    """Purge every tenant. Returns summed ``{table: deleted}``."""
    async with system_session() as session:
        tenant_ids = list((await session.execute(select(Tenant.id))).scalars().all())
    totals: dict[str, int] = {}
    for tid in tenant_ids:
        for table, count in (await purge_tenant(tid, now=now)).items():
            totals[table] = totals.get(table, 0) + count
    return totals
