from __future__ import annotations

from fastapi import APIRouter

from app.core.auth import CurrentTenant
from app.schemas.common import WhoAmIResponse

router = APIRouter()


@router.get("/whoami", response_model=WhoAmIResponse)
async def whoami(tenant: CurrentTenant) -> WhoAmIResponse:
    """Confirm the caller's authenticated tenant context, role, and how they authenticated."""
    return WhoAmIResponse(
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        role=tenant.role,
        auth_method=tenant.auth_method,
    )
