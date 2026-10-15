"""DTOs for connector discovery and credential management (Phase 2).

Credentials are **write-only** over the API: a secret goes in on create and is never returned —
``CredentialOut`` carries only non-secret metadata plus a redacted hint, so the client can show
"Slack · connected ••••ab12" without ever holding the token.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ToolOut(BaseModel):
    name: str
    title: str
    description: str
    capability: str
    scope: str
    input_schema: dict


class ConnectorOut(BaseModel):
    key: str
    name: str
    description: str
    capabilities: list[str]
    auth_type: str
    scopes: list[str]
    transport: str
    tools: list[ToolOut]


class CredentialCreate(BaseModel):
    connector_key: str = Field(..., min_length=1, max_length=64)
    name: str = Field(default="default", max_length=64)
    # The secret (OAuth access token or API key). Write-only; never returned.
    secret: str = Field(..., min_length=1)
    provider_meta: dict = Field(default_factory=dict)
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


class CredentialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    connector_key: str
    name: str
    auth_type: str
    provider_meta: dict
    scopes: list[str]
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
