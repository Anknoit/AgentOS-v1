from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    role: str
    created_at: datetime


class MemberCreate(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    role: str = Field(default="member")


class MemberRoleUpdate(BaseModel):
    role: str


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    role: str
    prefix: str
    user_id: str | None = None
    revoked: bool
    created_at: datetime
    last_used_at: datetime | None = None


class ApiKeyCreate(BaseModel):
    name: str = Field(default="default", max_length=128)
    role: str = Field(default="owner")
    user_id: str | None = None


class ApiKeyCreated(ApiKeyOut):
    # The plaintext key, returned exactly once at creation and never again.
    key: str


class SsoTokenRequest(BaseModel):
    """Mint a mock SSO token (dev/demo only; rejected unless ``sso_mode=mock``)."""

    subject: str = Field(..., min_length=1)
    email: str | None = None
    tenant: str | None = Field(default=None, description="tenant slug or id; defaults to caller")
    role: str | None = None
    ttl_seconds: int = Field(default=3600, ge=1, le=86400)


class SsoTokenResponse(BaseModel):
    token: str
    token_type: str = "Bearer"
    expires_in: int


class RolesResponse(BaseModel):
    roles: dict[str, list[str]]
