from sqlalchemy import Column, String, Float, DateTime, Boolean, JSON
from datetime import datetime
from app.persistence.db import Base


class DecisionModel(Base):
    __tablename__ = "decisions"

    decision_id = Column(String, primary_key=True, index=True)
    entity_id = Column(String, index=True)

    action_id = Column(String)
    action_type = Column(String)

    confidence = Column(Float)
    risk_level = Column(String)
    reasoning = Column(JSON)

    review_required = Column(Boolean)
    created_at = Column(DateTime, default=datetime.utcnow)


class OutcomeModel(Base):
    __tablename__ = "outcomes"

    decision_id = Column(String, primary_key=True)
    result = Column(String)
    impact_realized = Column(Float, nullable=True)
    feedback = Column(String, nullable=True)
    recorded_at = Column(DateTime, default=datetime.utcnow)
