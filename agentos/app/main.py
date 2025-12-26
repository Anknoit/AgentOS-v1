from fastapi import FastAPI
from app.api.nba import router as nba_router
from app.api.outcomes import router as outcome_router
from app.api.execute import router as execute_router

app = FastAPI(title="AgentOS – Next Best Action Engine")

app.include_router(nba_router)
app.include_router(outcome_router)
app.include_router(execute_router)


@app.get("/")
def health_check():
    return {"status": "AgentOS running"}
