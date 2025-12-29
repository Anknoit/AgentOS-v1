from fastapi import APIRouter
from app.api.schemas.telecom import TelecomIncidentRequest
from app.api.adapters.telecom_adapter import adapt_telecom_request
from app.core.decision_engine import DecisionEngine
from app.llm.client import LLMClient
from app.core.ontology.action import DEFAULT_ACTIONS

router = APIRouter(prefix="/telecom", tags=["Telecom"])


@router.post("/decide")
def telecom_decide(req: TelecomIncidentRequest):
    entity, signals, constraints = adapt_telecom_request(req)

    engine = DecisionEngine(llm_client=LLMClient())

    decision = engine.decide(
        entity=entity,
        signals=signals,
        constraints=constraints,
        actions=DEFAULT_ACTIONS,
    )

    return decision
