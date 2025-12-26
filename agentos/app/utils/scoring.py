from app.core.ontology.entity import Entity
from app.core.ontology.signal import Signal


def compute_urgency(entity: Entity, signals: list[Signal]) -> float:
    score = 0.0

    # Health deterioration
    score += (1 - entity.state.health_score) * 0.4

    # Time decay
    score += min(entity.state.time_in_state_hours / 72, 1) * 0.3

    # Signal volume
    score += min(len(signals) / 5, 1) * 0.3

    return round(score, 2)
