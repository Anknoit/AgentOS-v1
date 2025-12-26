from enum import Enum
from typing import Optional, List
from pydantic import BaseModel


class ActionType(str, Enum):
    NOTIFY = "Notify"
    RECOMMEND = "Recommend"
    EXECUTE = "Execute"
    ESCALATE = "Escalate"
    WAIT = "Wait"


class Action(BaseModel):
    action_id: str
    action_type: ActionType
    description: str
    requires_human: bool
    estimated_cost: Optional[float] = 0.0
    expected_impact: Optional[float] = 0.0


# ============================
# Default Action Registry
# ============================

WAIT_ACTION = Action(
    action_id="WAIT",
    action_type=ActionType.WAIT,
    description="Take no action and continue monitoring",
    requires_human=False,
    estimated_cost=0.0,
    expected_impact=0.0
)

NOTIFY_ACTION = Action(
    action_id="NOTIFY_OWNER",
    action_type=ActionType.NOTIFY,
    description="Notify entity owner with current status and insights",
    requires_human=False,
    estimated_cost=10.0,
    expected_impact=0.1
)

RECOMMEND_ACTION = Action(
    action_id="RECOMMEND_ACTION",
    action_type=ActionType.RECOMMEND,
    description="Recommend next step to responsible human",
    requires_human=True,
    estimated_cost=50.0,
    expected_impact=0.4
)

EXECUTE_ACTION = Action(
    action_id="EXECUTE_STANDARD_PLAYBOOK",
    action_type=ActionType.EXECUTE,
    description="Execute a predefined standard operating procedure",
    requires_human=False,
    estimated_cost=100.0,
    expected_impact=0.6
)

ESCALATE_ACTION = Action(
    action_id="ESCALATE",
    action_type=ActionType.ESCALATE,
    description="Escalate to senior or specialized team",
    requires_human=True,
    estimated_cost=200.0,
    expected_impact=0.8
)

DEFAULT_ACTIONS: List[Action] = [
    WAIT_ACTION,
    NOTIFY_ACTION,
    RECOMMEND_ACTION,
    EXECUTE_ACTION,
    ESCALATE_ACTION
]
