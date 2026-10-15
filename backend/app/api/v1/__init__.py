from fastapi import APIRouter

from app.api.v1 import agents, meta, runs, usage

api_router = APIRouter()
api_router.include_router(meta.router, tags=["meta"])
api_router.include_router(agents.router, prefix="/agents", tags=["agents"])
api_router.include_router(runs.router, prefix="/runs", tags=["runs"])
api_router.include_router(usage.router, prefix="/usage", tags=["usage"])

__all__ = ["api_router"]
