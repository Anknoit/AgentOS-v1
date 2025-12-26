from pydantic import BaseModel
from enum import Enum
from datetime import datetime


class EntityType(str, Enum):
    CUSTOMER = "Customer"
    DEAL = "Deal"
    ASSET = "Asset"
    INCIDENT = "Incident"
    TICKET = "Ticket"
    POSITION = "Position"


class State(BaseModel):
    status: str
    health_score: float
    last_updated: datetime
    time_in_state_hours: float


class Entity(BaseModel):
    entity_id: str
    entity_type: EntityType
    owner: str | None
    priority: int
    lifecycle_stage: str
    state: State
