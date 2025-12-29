from pydantic import BaseModel
from typing import List, Dict, Any


class TelecomSignal(BaseModel):
    name: str
    severity: str


class TelecomIncidentRequest(BaseModel):
    entity_id: str
    industry: str = "telecom"
    state: str
    vip_users: bool
    blast_radius: str
    sop_key: str | None = None
    signals: List[TelecomSignal]
    constraints: List[str] = []
