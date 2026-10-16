from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str
    version: str
    env: str
    database: str  # "postgres" | "sqlite"
    runtime: str  # "inprocess" | "arq"
    deployment_mode: str = "cloud"  # "cloud" | "self_hosted"
    region: str = "global"


class WhoAmIResponse(BaseModel):
    tenant_id: str
    user_id: str | None = None
    role: str = "owner"
    auth_method: str = "api_key"
