from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from app.persistence.db import SessionLocal
from app.persistence.repositories import OutcomeRepository

router = APIRouter(prefix="/outcomes", tags=["Outcomes"])


class OutcomeRequest(BaseModel):
    decision_id: str
    result: str  # Success | Partial | Failure
    impact_realized: Optional[float] = None
    feedback: Optional[str] = None
    recorded_at: Optional[datetime] = None


@router.post("/record")
def record_outcome(request: OutcomeRequest):
    db = SessionLocal()
    try:
        repo = OutcomeRepository(db)

        repo.save({
            "decision_id": request.decision_id,
            "result": request.result,
            "impact_realized": request.impact_realized,
            "feedback": request.feedback,
            "recorded_at": request.recorded_at or datetime.utcnow()
        })

        return {"status": "outcome recorded"}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()
