from pydantic import BaseModel
from enum import Enum
from datetime import datetime


class SignalType(str, Enum):
    BEHAVIORAL = "Behavioral"
    OPERATIONAL = "Operational"
    FINANCIAL = "Financial"
    MARKET = "Market"
    RISK = "Risk"


class Signal(BaseModel):
    signal_type: SignalType
    name: str
    value: str
    direction: str | None
    confidence: float
    timestamp: datetime
