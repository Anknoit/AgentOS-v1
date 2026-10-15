from __future__ import annotations

from pydantic import BaseModel, Field


class TriggerRunRequest(BaseModel):
    task: str = Field(..., min_length=1, description="The task prompt for the trivial agent loop")
    agent_id: str | None = None


class TriggerRunResponse(BaseModel):
    run_id: str
    enqueued: bool = Field(description="True if dispatched to a worker; False if run in-process")


class RunResultResponse(BaseModel):
    run_id: str
    status: str
    usage_event_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    output: str = ""
