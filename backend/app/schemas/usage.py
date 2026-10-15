from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UsageEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    idempotency_key: str
    event_type: str
    provider: str
    model: str | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    quantity: int
    unit: str
    run_id: str | None
    agent_id: str | None
    trace_id: str | None
    rated: bool
    occurred_at: datetime
