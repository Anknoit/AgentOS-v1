from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str
    version: str
    env: str
    database: str  # "postgres" | "sqlite"
    runtime: str  # "inprocess" | "arq"


class WhoAmIResponse(BaseModel):
    tenant_id: str
    user_id: str | None = None
