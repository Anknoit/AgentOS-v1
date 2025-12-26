from fastapi import APIRouter, HTTPException
from typing import List

from app.core.ontology.entity import Entity
from app.core.ontology.signal import Signal
from app.core.ontology.action import DEFAULT_ACTIONS
from app.core.ontology.decision import Decision
from app.core.decision_engine import DecisionEngine
from app.llm.client import LLMClient
from app.persistence.db import SessionLocal, init_db
from app.persistence.repositories import DecisionRepository

init_db()

router = APIRouter(prefix="/nba", tags=["Next Best Action"])


class NBARequest(Entity):
    signals: List[Signal]
    constraints: List[str]


@router.post("/decide", response_model=Decision)
def decide_next_action(request: NBARequest):
    db = SessionLocal()
    try:
        llm_client = LLMClient()  # mock LLM
        engine = DecisionEngine(llm_client)

        decision = engine.decide(
            entity=request,
            signals=request.signals,
            constraints=request.constraints,
            actions=DEFAULT_ACTIONS
        )

        DecisionRepository(db).save(decision)

        return decision
    finally:
        db.close()