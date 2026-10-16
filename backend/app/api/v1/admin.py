"""Operator endpoints for fraud/abuse holds (Phase 6). All require ``admin:write`` except the
read, which requires ``audit:read``.

* ``GET  /v1/admin/holds``                 — list holds for the tenant.
* ``POST /v1/admin/holds``                 — place a manual hold.
* ``POST /v1/admin/holds/scan``            — promote recent anomalies into a hold (operator scan).
* ``POST /v1/admin/holds/{id}/release``    — release a hold, unblocking billable work.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.compliance.audit import audit
from app.core.context import TenantContext
from app.fraud import controls
from app.identity.rbac import Scoped
from app.schemas.fraud import HoldCreate, HoldOut, HoldScanResult

router = APIRouter()


@router.get("/holds", response_model=list[HoldOut])
async def list_holds(
    tenant: Annotated[TenantContext, Scoped("audit:read")],
    active_only: bool = Query(default=False),
) -> list[HoldOut]:
    rows = await controls.list_holds(tenant.tenant_id, active_only=active_only)
    return [HoldOut.model_validate(r) for r in rows]


@router.post("/holds", response_model=HoldOut, status_code=201)
async def place_hold(
    body: HoldCreate, tenant: Annotated[TenantContext, Scoped("admin:write")]
) -> HoldOut:
    hold = await controls.place_hold(
        tenant.tenant_id, kind=body.kind, reason=body.reason, context=body.context
    )
    await audit(
        tenant, "hold.place", resource_type="tenant_hold", resource_id=hold.id,
        context={"kind": body.kind, "reason": body.reason},
    )
    return HoldOut.model_validate(hold)


@router.post("/holds/scan", response_model=HoldScanResult)
async def scan_for_holds(
    tenant: Annotated[TenantContext, Scoped("admin:write")],
) -> HoldScanResult:
    hold = await controls.evaluate_anomaly_holds(tenant.tenant_id)
    if hold is None:
        return HoldScanResult(placed=False)
    await audit(
        tenant, "hold.scan", resource_type="tenant_hold", resource_id=hold.id,
        context={"kind": hold.kind, "reason": hold.reason},
    )
    return HoldScanResult(placed=True, hold=HoldOut.model_validate(hold))


@router.post("/holds/{hold_id}/release", response_model=HoldOut)
async def release_hold(
    hold_id: str, tenant: Annotated[TenantContext, Scoped("admin:write")]
) -> HoldOut:
    released_by = tenant.user_id or "operator"
    hold = await controls.release_hold(tenant.tenant_id, hold_id, released_by=released_by)
    await audit(
        tenant, "hold.release", resource_type="tenant_hold", resource_id=hold_id,
    )
    return HoldOut.model_validate(hold)
