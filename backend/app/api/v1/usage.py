from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.core.auth import CurrentTenant
from app.db.session import tenant_session
from app.models.usage_event import UsageEvent
from app.schemas.usage import UsageEventOut

router = APIRouter()


@router.get("", response_model=list[UsageEventOut])
async def list_usage(
    tenant: CurrentTenant,
    run_id: str | None = Query(default=None),
    limit: int = Query(default=100, le=1000),
) -> list[UsageEventOut]:
    """List captured usage events for the tenant (newest first)."""
    async with tenant_session(tenant.tenant_id) as session:
        stmt = (
            select(UsageEvent)
            .where(UsageEvent.tenant_id == tenant.tenant_id)
            .order_by(UsageEvent.occurred_at.desc())
            .limit(limit)
        )
        if run_id:
            stmt = stmt.where(UsageEvent.run_id == run_id)
        rows = (await session.execute(stmt)).scalars().all()
        return [UsageEventOut.model_validate(r) for r in rows]
