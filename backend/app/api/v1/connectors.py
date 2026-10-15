"""Connector + credential endpoints (Phase 2).

* ``GET    /v1/connectors``                  — discover available connectors + their tools
* ``GET    /v1/connectors/{key}``            — one connector's spec
* ``GET    /v1/credentials``                 — list this tenant's stored credentials (no secrets)
* ``POST   /v1/credentials``                 — store/replace a credential (secret write-only)
* ``DELETE /v1/credentials/{connector_key}`` — remove a credential (``?name=`` optional)

The catalogue (connectors/tools) is public to any authenticated tenant; credentials are strictly
tenant-scoped and the secret is never returned.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Response

from app.core.auth import CurrentTenant
from app.schemas.connector import ConnectorOut, CredentialCreate, CredentialOut
from app.services import connectors as connectors_service
from app.services import credentials as vault

router = APIRouter()


@router.get("", response_model=list[ConnectorOut])
async def list_connectors(_tenant: CurrentTenant) -> list[ConnectorOut]:
    return connectors_service.list_connectors()


@router.get("/{key}", response_model=ConnectorOut)
async def get_connector(key: str, _tenant: CurrentTenant) -> ConnectorOut:
    return connectors_service.get_connector(key)


credentials_router = APIRouter()


@credentials_router.get("", response_model=list[CredentialOut])
async def list_credentials(tenant: CurrentTenant) -> list[CredentialOut]:
    rows = await vault.list_credentials(tenant.tenant_id)
    return [CredentialOut.model_validate(r) for r in rows]


@credentials_router.post("", response_model=CredentialOut, status_code=201)
async def put_credential(body: CredentialCreate, tenant: CurrentTenant) -> CredentialOut:
    cred = await vault.put_credential(
        tenant.tenant_id,
        connector_key=body.connector_key,
        secret=body.secret,
        name=body.name,
        provider_meta=body.provider_meta,
        scopes=body.scopes,
        expires_at=body.expires_at,
    )
    return CredentialOut.model_validate(cred)


@credentials_router.delete("/{connector_key}", status_code=204, response_class=Response)
async def delete_credential(
    connector_key: str,
    tenant: CurrentTenant,
    name: str = Query(default="default"),
) -> Response:
    await vault.delete_credential(tenant.tenant_id, connector_key, name)
    return Response(status_code=204)
