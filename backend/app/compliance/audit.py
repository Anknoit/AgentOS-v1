"""Control-plane audit trail (Phase 6, build task 1 — SOC 2).

``record_audit`` appends one row to the tenant-scoped, append-only ``audit_log`` naming *who did
what to which resource*, with the request trace id. It is written in its own committed transaction
so an audit entry survives even if the caller's later work rolls back — the trail must never lose a
mutation it was told about. Audit writes are best-effort relative to the operation: a failure to
record is logged, never raised, so auditing can't take down a working endpoint.

The whole trail is queryable and exportable (``GET /v1/audit`` / the export endpoint) for a review.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.config.settings import get_settings
from app.core.context import TenantContext, get_trace_id
from app.core.logging import get_logger
from app.db.session import tenant_session
from app.models.audit_log import AuditLog

log = get_logger(__name__)


async def record_audit(
    *,
    tenant_id: str,
    action: str,
    actor_id: str = "system",
    actor_type: str = "system",
    actor_role: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Append one audit entry (no-op if auditing is disabled). Never raises."""
    settings = get_settings()
    if not settings.audit_log_enabled:
        return
    try:
        async with tenant_session(tenant_id) as session:
            session.add(
                AuditLog(
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    actor_type=actor_type,
                    actor_role=actor_role,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    context=context or {},
                    trace_id=get_trace_id(),
                )
            )
    except Exception as exc:  # pragma: no cover - auditing must never break the operation
        log.error("audit.record_failed", action=action, tenant_id=tenant_id, error=str(exc))


async def audit(
    ctx: TenantContext,
    action: str,
    *,
    resource_type: str | None = None,
    resource_id: str | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Convenience: record an audit entry attributed to the authenticated principal ``ctx``."""
    await record_audit(
        tenant_id=ctx.tenant_id,
        action=action,
        actor_id=ctx.user_id or "unknown",
        actor_type=ctx.auth_method,
        actor_role=ctx.role,
        resource_type=resource_type,
        resource_id=resource_id,
        context=context,
    )


async def list_audit(
    tenant_id: str,
    *,
    action: str | None = None,
    since: datetime | None = None,
    limit: int = 500,
) -> list[AuditLog]:
    async with tenant_session(tenant_id) as session:
        stmt = (
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if since:
            stmt = stmt.where(AuditLog.created_at >= since)
        return list((await session.execute(stmt)).scalars().all())
