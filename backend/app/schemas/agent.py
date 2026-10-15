from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AgentVersionConfig(BaseModel):
    """The versioned, validated behaviour of an agent. Writing one mints an immutable version."""

    model: str = Field(default="gpt-4o-mini")
    system_prompt: str = Field(default="")
    tools: list[str] = Field(default_factory=list)
    guardrails: dict = Field(default_factory=dict)
    knowledge: list[str] = Field(default_factory=list)
    connector_bindings: dict = Field(default_factory=dict)


class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    # Prefill config from a built-in template (e.g. "support_desk"); explicit config overrides it.
    template: str | None = None
    role: str | None = None
    description: str | None = None
    config: AgentVersionConfig | None = None


class AgentUpdate(BaseModel):
    """Patch an agent. A new ``config`` mints a new immutable version and advances the pointer."""

    name: str | None = None
    role: str | None = None
    description: str | None = None
    status: str | None = Field(default=None, pattern="^(draft|active|paused|archived)$")
    config: AgentVersionConfig | None = None


class AgentVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    agent_id: str
    version: int
    model: str
    system_prompt: str
    tools: list[str]
    guardrails: dict
    knowledge: list[str]
    connector_bindings: dict
    created_at: datetime


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    template: str | None
    role: str | None
    description: str | None
    status: str
    current_version_id: str | None
    created_at: datetime
    updated_at: datetime
