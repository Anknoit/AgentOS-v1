"""Run endpoints — the Phase 0 agent-loop spike surface.

* ``POST /v1/runs`` — trigger a run. With Redis configured it is enqueued to an Arq worker;
  otherwise it executes in-process to completion (dev-fallback). Returns the run id.
* ``WS /v1/runs/stream`` — connect, send ``{"task": "..."}``, and receive streamed run events
  (``run_started``, ``token``, ``usage``, ``done``). This is the "stream tokens over WebSocket"
  spike. Authenticate with ``?token=<api-key>`` or an ``Authorization: Bearer`` header.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from app.config.settings import get_settings
from app.core.auth import CurrentTenant, resolve_api_key
from app.core.context import set_tenant, set_trace_id
from app.core.errors import AuthError
from app.core.logging import get_logger
from app.core.metrics import RUNS_STARTED
from app.runtime.agent import run_agent_loop
from app.runtime.queue import enqueue_run
from app.schemas.run import RunResultResponse, TriggerRunRequest, TriggerRunResponse

log = get_logger(__name__)
router = APIRouter()


@router.post("", response_model=TriggerRunResponse)
async def trigger_run(req: TriggerRunRequest, tenant: CurrentTenant) -> TriggerRunResponse:
    from app.core.context import get_trace_id

    run_id = uuid.uuid4().hex
    RUNS_STARTED.inc()
    settings = get_settings()

    if not settings.use_inprocess_runtime:
        await enqueue_run(
            tenant_id=tenant.tenant_id, task=req.task, run_id=run_id, trace_id=get_trace_id()
        )
        return TriggerRunResponse(run_id=run_id, enqueued=True)

    # In-process: run to completion and discard the stream (clients stream via the WS endpoint).
    async for _ in run_agent_loop(
        tenant_id=tenant.tenant_id, task=req.task, settings=settings, run_id=run_id,
        agent_id=req.agent_id,
    ):
        pass
    return TriggerRunResponse(run_id=run_id, enqueued=False)


@router.post("/sync", response_model=RunResultResponse)
async def run_sync(req: TriggerRunRequest, tenant: CurrentTenant) -> RunResultResponse:
    """Convenience: run in-process and return the full result (non-streaming)."""
    run_id = uuid.uuid4().hex
    RUNS_STARTED.inc()
    settings = get_settings()
    output: list[str] = []
    result = RunResultResponse(run_id=run_id, status="running")
    async for event in run_agent_loop(
        tenant_id=tenant.tenant_id, task=req.task, settings=settings, run_id=run_id,
        agent_id=req.agent_id,
    ):
        if event["type"] == "token":
            output.append(event["text"])
        elif event["type"] == "usage":
            result.usage_event_id = event["usage_event_id"]
            result.input_tokens = event["input_tokens"]
            result.output_tokens = event["output_tokens"]
            result.total_tokens = event["total_tokens"]
        elif event["type"] == "error":
            result.status = "error"
            result.output = event["message"]
            return result
    result.status = "completed"
    result.output = "".join(output)
    return result


def _bearer_from_headers(ws: WebSocket) -> str | None:
    auth = ws.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


@router.websocket("/stream")
async def stream_run(ws: WebSocket) -> None:
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
        RUNS_STARTED.inc()
        async for event in run_agent_loop(
            tenant_id=ctx.tenant_id, task=task, settings=get_settings()
        ):
            await ws.send_json(event)
        await ws.close()
    except WebSocketDisconnect:
        log.info("ws.disconnect")
