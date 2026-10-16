from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    actor_id: str
    actor_type: str
    actor_role: str | None = None
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    context: dict
    trace_id: str | None = None
    created_at: datetime


class SecurityPostureOut(BaseModel):
    """The security-review snapshot (free-form by design — see compliance.report)."""

    deployment_mode: str
    single_tenant: bool
    data_region: str
    environment: str
    tenant_isolation: str
    encryption: dict[str, Any]
    identity: dict[str, Any]
    audit: dict[str, Any]
    fraud_controls: dict[str, Any]
    dev_secrets_in_use: bool
    review_warnings: list[str]
    review_ready: bool


class RetentionResult(BaseModel):
    retention_days: int
    deleted: dict[str, int]


class KeyRotationResult(BaseModel):
    rotated: dict[str, int]
    total: int
