from app.core.ontology.action import Action
from app.core.ontology.decision import RiskLevel


def assess_risk(action: Action, confidence: float) -> RiskLevel:
    if action.requires_human:
        return RiskLevel.HIGH

    if confidence < 0.5:
        return RiskLevel.HIGH

    if action.estimated_cost and action.estimated_cost > 10000:
        return RiskLevel.MEDIUM

    return RiskLevel.LOW
