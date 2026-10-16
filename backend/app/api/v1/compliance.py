"""Compliance endpoints (Phase 6): audit export, security posture, retention, key rotation.

* ``GET  /v1/audit``                  — the tenant's control-plane audit trail (audit:read).
* ``GET  /v1/compliance/report``      — the security-posture snapshot for a review (audit:read).
* ``POST /v1/compliance/retention/purge`` — enforce the retention policy now (admin:write).
* ``POST /v1/compliance/keys/rotate`` — re-encrypt this tenant's vault under the current key
  (admin:write).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.compliance import retention
from app.compliance.audit import audit, list_audit
from app.compliance.keyrotation import rotate_tenant_credentials
from app.compliance.report import security_posture
from app.config.settings import get_settings
from app.core.context import TenantContext
from app.identity.rbac import Scoped
from app.schemas.compliance import (
    AuditLogOut,
    KeyRotationResult,
    RetentionResult,
    SecurityPostureOut,
)

audit_router = APIRouter()
router = APIRouter()


@audit_router.get("", response_model=list[AuditLogOut])
async def get_audit_log(
    tenant: Annotated[TenantContext, Scoped("audit:read")],
    action: str | None = Query(default=None),
    since: Annotated[datetime | None, Query()] = None,
    limit: int = Query(default=500, le=5000),
) -> list[AuditLogOut]:
    rows = await list_audit(tenant.tenant_id, action=action, since=since, limit=limit)
    return [AuditLogOut.model_validate(r) for r in rows]


@router.get("/report", response_model=SecurityPostureOut)
async def get_posture(
    _tenant: Annotated[TenantContext, Scoped("audit:read")],
) -> SecurityPostureOut:
    return SecurityPostureOut.model_validate(security_posture(get_settings()))


@router.post("/retention/purge", response_model=RetentionResult)
async def purge_retention(
    tenant: Annotated[TenantContext, Scoped("admin:write")],
) -> RetentionResult:
    deleted = await retention.purge_tenant(tenant.tenant_id)
    await audit(tenant, "retention.purge", context={"deleted": deleted})
    return RetentionResult(
        retention_days=get_settings().data_retention_days, deleted=deleted
    )


@router.post("/keys/rotate", response_model=KeyRotationResult)
async def rotate_keys(
    tenant: Annotated[TenantContext, Scoped("admin:write")],
) -> KeyRotationResult:
    count = await rotate_tenant_credentials(tenant.tenant_id)
    await audit(tenant, "keys.rotate", context={"credentials": count})
    return KeyRotationResult(rotated={tenant.tenant_id: count}, total=count)
