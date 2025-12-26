from datetime import datetime
from typing import List
import uuid

from app.core.ontology.entity import Entity
from app.core.ontology.signal import Signal
from app.core.ontology.action import Action
from app.core.ontology.decision import Decision, RiskLevel
from app.core.risk_engine import assess_risk
from app.utils.scoring import compute_urgency
from app.llm.client import LLMClient
from app.llm.prompts import nba_prompt
from app.llm.parser import parse_llm_response


class DecisionEngine:
    """
    Core Next-Best-Action decision engine
    """

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def decide(
        self,
        entity: Entity,
        signals: List[Signal],
        constraints: List[str],
        actions: List[Action]
    ) -> Decision:

        # 1. Filter actions via constraints
        allowed_actions = self._filter_actions(actions, constraints)

        if not allowed_actions:
            raise ValueError("No valid actions available after applying constraints")

        # 2. Compute urgency (deterministic)
        urgency_score = compute_urgency(entity, signals)

        # 3. Ask LLM to rank actions
        prompt = nba_prompt(
            entity=entity,
            signals=signals,
            actions=allowed_actions,
            urgency=urgency_score
        )

        try:
            llm_raw = self.llm.reason(prompt)
            print("LLM RAW OUTPUT >>>", repr(llm_raw))
            llm_decision = parse_llm_response(llm_raw)
        except Exception as e:
            print("LLM EXCEPTION >>>", repr(e))
            llm_decision = {
                "action": next(a for a in actions if a.action_id == "ESCALATE"),
                "confidence": 0.3,
                "reasoning": ["LLM failure, escalating by default"]
            }



        # 4. Calibrate confidence
        confidence = self._calibrate_confidence(
            llm_decision["confidence"],
            urgency_score
        )

        # 5. Assess risk
        risk_level = assess_risk(
            action=llm_decision["action"],
            confidence=confidence
        )

        # 6. Build Decision object
        decision = Decision(
            decision_id=str(uuid.uuid4()),
            entity_id=entity.entity_id,
            recommended_action=llm_decision["action"],
            confidence=confidence,
            risk_level=risk_level,
            reasoning=llm_decision["reasoning"],
            review_required=risk_level != RiskLevel.LOW,
            created_at=datetime.utcnow()
        )

        return decision

    def _filter_actions(self, actions: List[Action], constraints: List[str]) -> List[Action]:
        """
        Hard constraint filtering
        """
        filtered = []
        for action in actions:
            violated = False
            for rule in constraints:
                if rule.lower() in action.description.lower():
                    violated = True
                    break
            if not violated:
                filtered.append(action)
        return filtered

    def _calibrate_confidence(self, llm_conf: float, urgency: float) -> float:
        """
        Blend AI confidence with deterministic urgency
        """
        return round((llm_conf * 0.6) + (urgency * 0.4), 2)
