from fastapi import APIRouter, HTTPException
from app.persistence.db import SessionLocal
from app.persistence.models import DecisionModel
from app.core.execution.dispatcher import ExecutionDispatcher

router = APIRouter(prefix="/execute", tags=["Execution"])


@router.post("/{decision_id}")
def execute_decision(decision_id: str):
    db = SessionLocal()
    try:
        record = (
            db.query(DecisionModel)
            .filter(DecisionModel.decision_id == decision_id)
            .first()
        )

        if not record:
            raise HTTPException(status_code=404, detail="Decision not found")

        dispatcher = ExecutionDispatcher()
        result = dispatcher.dispatch(record)

        return {
            "decision_id": decision_id,
            "execution_result": result
        }

    finally:
        db.close()
