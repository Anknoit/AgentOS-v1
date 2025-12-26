import requests
from app.core.execution.base import ExecutionAdapter
from app.core.ontology.decision import Decision


class WebhookExecutor(ExecutionAdapter):
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def execute(self, decision: Decision) -> dict:
        payload = {
            "decision_id": decision.decision_id,
            "entity_id": decision.entity_id,
            "action": decision.recommended_action.action_id,
            "confidence": decision.confidence,
            "risk_level": decision.risk_level,
            "reasoning": decision.reasoning,
        }

        response = requests.post(self.webhook_url, json=payload, timeout=5)

        return {
            "status": "sent",
            "http_status": response.status_code
        }
