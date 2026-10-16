"""Marketplace endpoints (Phase 6, build task 4).

* ``GET  /v1/marketplace``                   — browse the public catalogue (marketplace:read).
* ``POST /v1/marketplace/publish/agent``     — publish an agent template (marketplace:write).
* ``POST /v1/marketplace/publish/connector`` — publish a connector config (marketplace:write).
* ``POST /v1/marketplace/{id}/install``      — install into the caller's tenant (marketplace:write).

Listings are cross-tenant by design; installs write only into the caller's tenant. Secrets are
never published or installed.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.compliance.audit import audit
from app.core.context import TenantContext
from app.identity.rbac import Scoped
from app.marketplace import service
from app.schemas.marketplace import (
    InstallRequest,
    InstallResult,
    ListingOut,
    PublishAgentRequest,
    PublishConnectorRequest,
)

router = APIRouter()


@router.get("", response_model=list[ListingOut])
async def browse(
    _tenant: Annotated[TenantContext, Scoped("marketplace:read")],
    kind: str | None = Query(default=None),
) -> list[ListingOut]:
    rows = await service.list_listings(kind=kind)
    return [ListingOut.model_validate(r) for r in rows]


@router.post("/publish/agent", response_model=ListingOut, status_code=201)
async def publish_agent(
    body: PublishAgentRequest, tenant: Annotated[TenantContext, Scoped("marketplace:write")]
) -> ListingOut:
    listing = await service.publish_agent(
        tenant.tenant_id, body.agent_id, name=body.name, description=body.description
    )
    await audit(
        tenant, "marketplace.publish", resource_type="listing", resource_id=listing.id,
        context={"kind": listing.kind, "slug": listing.slug},
    )
    return ListingOut.model_validate(listing)


@router.post("/publish/connector", response_model=ListingOut, status_code=201)
async def publish_connector(
    body: PublishConnectorRequest,
    tenant: Annotated[TenantContext, Scoped("marketplace:write")],
) -> ListingOut:
    listing = await service.publish_connector(
        tenant.tenant_id,
        connector_key=body.connector_key,
        name=body.name,
        description=body.description,
        provider_meta=body.provider_meta,
    )
    await audit(
        tenant, "marketplace.publish", resource_type="listing", resource_id=listing.id,
        context={"kind": listing.kind, "slug": listing.slug},
    )
    return ListingOut.model_validate(listing)


@router.post("/{listing_id}/install", response_model=InstallResult)
async def install(
    listing_id: str,
    tenant: Annotated[TenantContext, Scoped("marketplace:write")],
    body: InstallRequest | None = None,
) -> InstallResult:
    result = await service.install(
        tenant.tenant_id, listing_id, name=(body.name if body else None)
    )
    await audit(
        tenant, "marketplace.install", resource_type="listing", resource_id=listing_id,
        context={"kind": result.get("kind"), "slug": result.get("slug")},
    )
    return InstallResult.model_validate(result)
