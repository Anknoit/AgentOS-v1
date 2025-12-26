from fastapi import FastAPI
from app.api.nba import router as nba_router

app = FastAPI(title="AgentOS – Next Best Action Engine")

app.include_router(nba_router)


@app.get("/")
def health_check():
    return {"status": "AgentOS running"}
