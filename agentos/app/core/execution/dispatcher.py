from app.core.ontology.decision import Decision
from app.core.ontology.action import ActionType
from app.core.execution.webhook_executor import WebhookExecutor


class ExecutionDispatcher:
    def __init__(self):
        # Later this becomes config-driven
        self.webhook_executor = WebhookExecutor(
            webhook_url="http://localhost:9000/agent-hook"
        )

    def dispatch(self, decision: Decision) -> dict:
        action_type = decision.recommended_action.action_type

        if action_type in [ActionType.EXECUTE, ActionType.NOTIFY]:
            return self.webhook_executor.execute(decision)

        return {
            "status": "skipped",
            "reason": f"Action type {action_type} requires human handling"
        }
