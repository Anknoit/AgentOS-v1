from sqlalchemy.orm import Session
from app.persistence.models import DecisionModel, OutcomeModel
from app.core.ontology.decision import Decision


class DecisionRepository:
    def __init__(self, db: Session):
        self.db = db

    def save(self, decision: Decision):
        record = DecisionModel(
            decision_id=decision.decision_id,
            entity_id=decision.entity_id,
            action_id=decision.recommended_action.action_id,
            action_type=decision.recommended_action.action_type,
            confidence=decision.confidence,
            risk_level=decision.risk_level,
            reasoning=decision.reasoning,
            review_required=decision.review_required,
            created_at=decision.created_at,
        )
        self.db.add(record)
        self.db.commit()


class OutcomeRepository:
    def __init__(self, db: Session):
        self.db = db

    def save(self, outcome: dict):
        record = OutcomeModel(**outcome)
        self.db.add(record)
        self.db.commit()
