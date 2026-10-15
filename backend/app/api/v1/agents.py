"""Agent endpoints — the client-facing control surface for the fleet.

* ``POST   /v1/agents``                      — create an agent (from a template or explicit config)
* ``GET    /v1/agents``                      — list agents
* ``GET    /v1/agents/{agent_id}``           — get one agent
* ``PATCH  /v1/agents/{agent_id}``           — update; a new config mints a new immutable version
* ``GET    /v1/agents/{agent_id}/versions``  — list the agent's versions
* ``POST   /v1/agents/{agent_id}/runs``      — trigger a run (returns the completed run in-process)
* ``WS     /v1/agents/{agent_id}/runs/stream`` — trigger + stream run events live
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from app.core.auth import CurrentTenant, resolve_api_key
from app.core.context import get_trace_id, set_tenant, set_trace_id
from app.core.errors import AuthError, NotFoundError
from app.core.logging import get_logger
from app.core.metrics import RUNS_STARTED
from app.runtime.manager import get_run_manager
from app.runtime.store import get_run
from app.schemas.agent import AgentCreate, AgentOut, AgentUpdate, AgentVersionOut
from app.schemas.run import RunOut, TriggerRunRequest
from app.services import agents as agents_service
from app.services import runs as runs_service

log = get_logger(__name__)
router = APIRouter()


@router.post("", response_model=AgentOut, status_code=201)
async def create_agent(body: AgentCreate, tenant: CurrentTenant) -> AgentOut:
    agent = await agents_service.create_agent(tenant.tenant_id, body)
    return AgentOut.model_validate(agent)


@router.get("", response_model=list[AgentOut])
async def list_agents(tenant: CurrentTenant) -> list[AgentOut]:
    agents = await agents_service.list_agents(tenant.tenant_id)
    return [AgentOut.model_validate(a) for a in agents]


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: str, tenant: CurrentTenant) -> AgentOut:
    agent = await agents_service.get_agent(tenant.tenant_id, agent_id)
    return AgentOut.model_validate(agent)


@router.patch("/{agent_id}", response_model=AgentOut)
async def update_agent(agent_id: str, body: AgentUpdate, tenant: CurrentTenant) -> AgentOut:
    agent = await agents_service.update_agent(tenant.tenant_id, agent_id, body)
    return AgentOut.model_validate(agent)


@router.get("/{agent_id}/versions", response_model=list[AgentVersionOut])
async def list_versions(agent_id: str, tenant: CurrentTenant) -> list[AgentVersionOut]:
    versions = await agents_service.list_versions(tenant.tenant_id, agent_id)
    return [AgentVersionOut.model_validate(v) for v in versions]


@router.post("/{agent_id}/runs", response_model=RunOut, status_code=201)
async def trigger_agent_run(
    agent_id: str, body: TriggerRunRequest, tenant: CurrentTenant
) -> RunOut:
    """Trigger a run. In-process, waits for completion and returns the finished run."""
    agent = await agents_service.get_agent(tenant.tenant_id, agent_id)
    version = await agents_service.resolve_current_version(tenant.tenant_id, agent)
    RUNS_STARTED.inc()
    run_id, enqueued = await runs_service.trigger_run(
        tenant_id=tenant.tenant_id,
        agent=agent,
        version=version,
        task=body.task,
        trace_id=get_trace_id(),
    )
    if not enqueued:
        await get_run_manager().wait(run_id)
    run = await get_run(tenant.tenant_id, run_id)
    if run is None:  # pragma: no cover - the row was just created
        raise NotFoundError(f"run '{run_id}' not found")
    return RunOut.model_validate(run)


def _bearer_from_headers(ws: WebSocket) -> str | None:
    auth = ws.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


@router.websocket("/{agent_id}/runs/stream")
async def stream_agent_run(ws: WebSocket, agent_id: str) -> None:
    token = ws.query_params.get("token") or _bearer_from_headers(ws)
    if not token:
        await ws.close(code=4401)
        return
    try:
        ctx = await resolve_api_key(token)
    except AuthError:
        await ws.close(code=4401)
        return

    set_tenant(ctx)
    set_trace_id(ws.headers.get("x-trace-id"))
    await ws.accept()

    try:
        msg = await ws.receive_json()
        task = (msg or {}).get("task")
        if not task:
            await ws.send_json({"type": "error", "message": "missing 'task'"})
            await ws.close(code=4400)
            return
        try:
            agent = await agents_service.get_agent(ctx.tenant_id, agent_id)
            version = await agents_service.resolve_current_version(ctx.tenant_id, agent)
        except NotFoundError as exc:
            await ws.send_json({"type": "error", "message": str(exc)})
            await ws.close(code=4404)
            return

        RUNS_STARTED.inc()
        run_id, _ = await runs_service.trigger_run(
            tenant_id=ctx.tenant_id,
            agent=agent,
            version=version,
            task=task,
            trace_id=get_trace_id(),
        )
        # The run executes as a managed job; this socket only observes it. A disconnect here
        # leaves the run running server-side (it completes and is fully logged regardless).
        async for event in get_run_manager().subscribe(run_id):
            await ws.send_json(event)
        await ws.close()
    except WebSocketDisconnect:
        log.info("ws.disconnect", agent_id=agent_id)
