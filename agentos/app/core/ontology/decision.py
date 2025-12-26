from pydantic import BaseModel
from enum import Enum
from datetime import datetime
from typing import List

from app.core.ontology.action import Action


class RiskLevel(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class Decision(BaseModel):
    decision_id: str
    entity_id: str
    recommended_action: Action
    confidence: float
    risk_level: RiskLevel
    reasoning: List[str]
    review_required: bool
    created_at: datetime
