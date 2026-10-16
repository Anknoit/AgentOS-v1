"""Member + API-key management endpoints (Phase 6, RBAC).

All writes require ``members:write`` (owner/admin); reads require ``members:read``. A minted API
key's plaintext is returned exactly once. Every mutation is recorded to the audit log.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Response

from app.compliance.audit import audit
from app.core.context import TenantContext
from app.identity import members as members_service
from app.identity.rbac import Scoped
from app.schemas.identity import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    MemberCreate,
    MemberOut,
    MemberRoleUpdate,
)

router = APIRouter()
api_keys_router = APIRouter()


@router.get("", response_model=list[MemberOut])
async def list_members(
    tenant: Annotated[TenantContext, Scoped("members:read")],
) -> list[MemberOut]:
    rows = await members_service.list_members(tenant.tenant_id)
    return [MemberOut.model_validate(r) for r in rows]


@router.post("", response_model=MemberOut, status_code=201)
async def create_member(
    body: MemberCreate, tenant: Annotated[TenantContext, Scoped("members:write")]
) -> MemberOut:
    user = await members_service.create_member(
        tenant.tenant_id, email=body.email, role=body.role
    )
    await audit(
        tenant, "member.create", resource_type="user", resource_id=user.id,
        context={"email": body.email, "role": body.role},
    )
    return MemberOut.model_validate(user)


@router.patch("/{user_id}", response_model=MemberOut)
async def update_member(
    user_id: str,
    body: MemberRoleUpdate,
    tenant: Annotated[TenantContext, Scoped("members:write")],
) -> MemberOut:
    user = await members_service.update_member_role(tenant.tenant_id, user_id, role=body.role)
    await audit(
        tenant, "member.update_role", resource_type="user", resource_id=user_id,
        context={"role": body.role},
    )
    return MemberOut.model_validate(user)


@router.delete("/{user_id}", status_code=204, response_class=Response)
async def delete_member(
    user_id: str, tenant: Annotated[TenantContext, Scoped("members:write")]
) -> Response:
    await members_service.delete_member(tenant.tenant_id, user_id)
    await audit(tenant, "member.delete", resource_type="user", resource_id=user_id)
    return Response(status_code=204)


@api_keys_router.get("", response_model=list[ApiKeyOut])
async def list_api_keys(
    tenant: Annotated[TenantContext, Scoped("members:read")],
) -> list[ApiKeyOut]:
    rows = await members_service.list_api_keys(tenant.tenant_id)
    return [ApiKeyOut.model_validate(r) for r in rows]


@api_keys_router.post("", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(
    body: ApiKeyCreate, tenant: Annotated[TenantContext, Scoped("members:write")]
) -> ApiKeyCreated:
    key, raw = await members_service.create_api_key(
        tenant.tenant_id, name=body.name, role=body.role, user_id=body.user_id
    )
    await audit(
        tenant, "apikey.create", resource_type="api_key", resource_id=key.id,
        context={"name": body.name, "role": body.role},
    )
    return ApiKeyCreated(**ApiKeyOut.model_validate(key).model_dump(), key=raw)


@api_keys_router.delete("/{key_id}", status_code=204, response_class=Response)
async def revoke_api_key(
    key_id: str, tenant: Annotated[TenantContext, Scoped("members:write")]
) -> Response:
    await members_service.revoke_api_key(tenant.tenant_id, key_id)
    await audit(tenant, "apikey.revoke", resource_type="api_key", resource_id=key_id)
    return Response(status_code=204)
