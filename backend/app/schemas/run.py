from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TriggerRunRequest(BaseModel):
    task: str = Field(..., min_length=1, description="The task prompt for the agent run")
    agent_id: str | None = None


class TriggerRunResponse(BaseModel):
    run_id: str
    enqueued: bool = Field(description="True if dispatched to a worker; False if run in-process")


class RunResultResponse(BaseModel):
    """Full result of an in-process run (Phase 0 spike + agent sync run)."""

    run_id: str
    status: str
    usage_event_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    output: str = ""


class RunOut(BaseModel):
    """An agent run (control record)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_id: str | None
    agent_version_id: str | None
    status: str
    task: str
    output: str | None
    error: str | None
    trace_id: str | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    tool_calls: int
    step_count: int
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


class ActionLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    seq: int
    type: str
    name: str | None
    content: dict
    usage_event_id: str | None
    trace_id: str | None
    created_at: datetime
