"""SSO / identity endpoints (Phase 6).

* ``GET  /v1/auth/roles``      — the RBAC role → permission matrix (discovery for the UI).
* ``POST /v1/auth/sso/token``  — mint a **mock** SSO token for a member (dev/demo only; rejected
  unless ``AGENTOS_SSO_MODE=mock``). This is how the offline SSO flow is exercised end to end: the
  minted JWT is then presented as ``Authorization: Bearer`` to any endpoint and resolves to the
  member's tenant + role. A real OIDC deployment mints tokens at the IdP, not here.

Resolving an SSO token on a request is handled transparently in ``core.auth`` — any endpoint
accepts either an API key or an SSO JWT.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.config.settings import get_settings
from app.core.auth import CurrentTenant
from app.core.errors import ForbiddenError
from app.identity.oidc import mint_mock_token
from app.identity.rbac import ROLE_PERMISSIONS
from app.schemas.identity import RolesResponse, SsoTokenRequest, SsoTokenResponse

router = APIRouter()


@router.get("/roles", response_model=RolesResponse)
async def list_roles(_tenant: CurrentTenant) -> RolesResponse:
    return RolesResponse(roles={r: sorted(p) for r, p in ROLE_PERMISSIONS.items()})


@router.post("/sso/token", response_model=SsoTokenResponse)
async def mint_sso_token(payload: SsoTokenRequest, tenant: CurrentTenant) -> SsoTokenResponse:
    settings = get_settings()
    if settings.sso_mode != "mock":
        raise ForbiddenError(
            "mock SSO token minting is only available when AGENTOS_SSO_MODE=mock"
        )
    token = mint_mock_token(
        settings,
        subject=payload.subject,
        email=payload.email,
        tenant=payload.tenant or tenant.tenant_id,
        role=payload.role,
        ttl_seconds=payload.ttl_seconds,
    )
    return SsoTokenResponse(token=token, expires_in=payload.ttl_seconds)
