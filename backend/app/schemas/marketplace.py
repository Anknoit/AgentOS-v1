from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ListingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    publisher_tenant_id: str
    kind: str
    slug: str
    name: str
    description: str | None = None
    config: dict
    installs: int
    created_at: datetime


class PublishAgentRequest(BaseModel):
    agent_id: str
    name: str | None = Field(default=None, max_length=128)
    description: str | None = None


class PublishConnectorRequest(BaseModel):
    connector_key: str
    name: str = Field(..., max_length=128)
    description: str | None = None
    provider_meta: dict = Field(default_factory=dict)


class InstallRequest(BaseModel):
    name: str | None = Field(default=None, max_length=128)


class InstallResult(BaseModel):
    kind: str
    slug: str
    agent_id: str | None = None
    connector_key: str | None = None
    provider_meta: dict | None = None
    note: str | None = None
