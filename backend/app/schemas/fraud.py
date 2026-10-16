from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class HoldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    reason: str
    active: bool
    context: dict
    created_at: datetime
    released_at: datetime | None = None
    released_by: str | None = None


class HoldCreate(BaseModel):
    reason: str = Field(..., min_length=1, max_length=255)
    kind: str = Field(default="manual")
    context: dict = Field(default_factory=dict)


class HoldScanResult(BaseModel):
    placed: bool
    hold: HoldOut | None = None
