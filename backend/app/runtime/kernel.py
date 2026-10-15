"""The agent runtime kernel (Phase 1).

An agent run executes as a **LangGraph ``StateGraph`` with checkpointing**. The Support Desk
graph is linear — ``triage → retrieve → respond → finalize`` — but it exercises every seam the
fleet needs:

* **action logging** — each node appends to the append-only ``action_log`` with the trace id;
* **metering hooks** — the tool node and the model node each capture one ``usage_event`` with a
  deterministic idempotency key (``{run_id}:step{seq}:{kind}``), so a node that replays after a
  resume never double-counts;
* **streaming** — nodes push events (tokens, tool calls, usage) onto an ``EventSink`` the caller
  drains and relays over the WebSocket;
* **durability** — the graph's checkpointer persists state after each node, so a run resumes from
  where it stopped (``resume=True``) across a worker restart.

``execute_run`` is an async generator of run events; the API and the Arq worker both drive it.
"""

from __future__ import annotations

import asyncio
import operator
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.config.settings import Settings
from app.core.logging import get_logger
from app.core.tracing import start_span
from app.db.session import tenant_session
from app.metering.usage import UsageRecord, capture_usage
from app.runtime import store
from app.runtime.checkpointer import checkpointer_cm
from app.runtime.providers import get_provider
from app.runtime.tools import get_tool

log = get_logger(__name__)

_SENTINEL = object()


class EventSink:
    """A one-run async channel: graph nodes ``emit`` events; the driver ``stream``s them out."""

    def __init__(self) -> None:
        self._q: asyncio.Queue[Any] = asyncio.Queue()

    async def emit(self, event: dict) -> None:
        await self._q.put(event)

    async def close(self) -> None:
        await self._q.put(_SENTINEL)

    async def stream(self) -> AsyncIterator[dict]:
        while True:
            ev = await self._q.get()
            if ev is _SENTINEL:
                return
            yield ev


@dataclass
class RunContext:
    tenant_id: str
    run_id: str
    agent_id: str | None
    agent_version_id: str | None
    model: str
    system_prompt: str
    tools: list[str]
    trace_id: str | None
    settings: Settings


class AgentState(TypedDict, total=False):
    task: str
    retrieved: list[str]
    draft: str
    output: str
    seq: int
    input_tokens: int
    output_tokens: int
    tool_calls: Annotated[int, operator.add]


def _build_graph(ctx: RunContext, sink: EventSink, saver: object):
    provider = get_provider(ctx.settings)

    async def triage(state: AgentState) -> AgentState:
        seq = state.get("seq", 1)
        await store.append_action(
            tenant_id=ctx.tenant_id,
            run_id=ctx.run_id,
            seq=seq,
            type="node",
            name="triage",
            content={"intent": "support_question", "task": state["task"]},
            trace_id=ctx.trace_id,
        )
        await sink.emit({"type": "node", "run_id": ctx.run_id, "name": "triage", "seq": seq})
        return {"seq": seq + 1}

    async def retrieve(state: AgentState) -> AgentState:
        seq = state.get("seq", 2)
        tool_name = "kb_search"
        results: list[str] = []
        usage_event_id: str | None = None
        tool = get_tool(tool_name)
        if tool is not None and tool_name in ctx.tools:
            result = await tool({"query": state["task"]})
            results = result.output.get("results", [])
            # One usage_event per tool call (metered now, rated in Phase 3).
            with start_span("metering.capture_usage", **{"usage.kind": "tool_call"}):
                async with tenant_session(ctx.tenant_id) as session:
                    event = await capture_usage(
                        session,
                        UsageRecord(
                            tenant_id=ctx.tenant_id,
                            idempotency_key=f"{ctx.run_id}:step{seq}:tool:{tool_name}",
                            event_type="tool_call",
                            provider="tool",
                            model=None,
                            quantity=result.quantity,
                            unit=result.unit,
                            run_id=ctx.run_id,
                            agent_id=ctx.agent_id,
                            trace_id=ctx.trace_id,
                        ),
                    )
                    usage_event_id = event.id
        await store.append_action(
            tenant_id=ctx.tenant_id,
            run_id=ctx.run_id,
            seq=seq,
            type="tool_call",
            name=tool_name,
            content={"query": state["task"], "results": results},
            usage_event_id=usage_event_id,
            trace_id=ctx.trace_id,
        )
        await sink.emit(
            {
                "type": "tool_call",
                "run_id": ctx.run_id,
                "name": tool_name,
                "seq": seq,
                "results": results,
                "usage_event_id": usage_event_id,
            }
        )
        return {"retrieved": results, "tool_calls": 1, "seq": seq + 1}

    async def respond(state: AgentState) -> AgentState:
        seq = state.get("seq", 3)
        context_block = "\n".join(f"- {r}" for r in state.get("retrieved", []))
        prompt = (
            f"{ctx.system_prompt}\n\nKnowledge base:\n{context_block}\n\n"
            f"Customer: {state['task']}"
        )
        text_parts: list[str] = []
        input_tokens = output_tokens = 0
        with start_span("provider.chat.stream", **{"llm.model": ctx.model}):
            async for chunk in provider.stream(prompt, model=ctx.model):
                if chunk.delta:
                    text_parts.append(chunk.delta)
                    await sink.emit(
                        {"type": "token", "run_id": ctx.run_id, "text": chunk.delta}
                    )
                if chunk.done and chunk.usage is not None:
                    input_tokens = chunk.usage.input_tokens
                    output_tokens = chunk.usage.output_tokens
        draft = "".join(text_parts)

        with start_span("metering.capture_usage", **{"usage.kind": "model_call"}):
            async with tenant_session(ctx.tenant_id) as session:
                event = await capture_usage(
                    session,
                    UsageRecord(
                        tenant_id=ctx.tenant_id,
                        idempotency_key=f"{ctx.run_id}:step{seq}:model_call",
                        event_type="model_call",
                        provider=provider.name,
                        model=ctx.model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        run_id=ctx.run_id,
                        agent_id=ctx.agent_id,
                        trace_id=ctx.trace_id,
                    ),
                )
                usage_event_id = event.id
        await store.append_action(
            tenant_id=ctx.tenant_id,
            run_id=ctx.run_id,
            seq=seq,
            type="model_call",
            name=ctx.model,
            content={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "text": draft,
            },
            usage_event_id=usage_event_id,
            trace_id=ctx.trace_id,
        )
        await sink.emit(
            {
                "type": "usage",
                "run_id": ctx.run_id,
                "usage_event_id": usage_event_id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            }
        )
        return {
            "draft": draft,
            "input_tokens": state.get("input_tokens", 0) + input_tokens,
            "output_tokens": state.get("output_tokens", 0) + output_tokens,
            "seq": seq + 1,
        }

    async def finalize(state: AgentState) -> AgentState:
        retrieved = state.get("retrieved", [])
        grounding = f"\n\nBased on our knowledge base: {retrieved[0]}" if retrieved else ""
        output = state.get("draft", "") + grounding
        return {"output": output}

    graph = StateGraph(AgentState)
    graph.add_node("triage", triage)
    graph.add_node("retrieve", retrieve)
    graph.add_node("respond", respond)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "triage")
    graph.add_edge("triage", "retrieve")
    graph.add_edge("retrieve", "respond")
    graph.add_edge("respond", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=saver)


async def execute_run(ctx: RunContext, *, task: str, resume: bool = False) -> AsyncIterator[dict]:
    """Drive one agent run as a graph, yielding run events and persisting the audit trail."""
    sink = EventSink()
    result: dict[str, Any] = {}
    error: dict[str, Any] = {}

    async def _drive() -> None:
        try:
            async with checkpointer_cm(ctx.settings) as saver:
                app = _build_graph(ctx, sink, saver)
                cfg = {"configurable": {"thread_id": ctx.run_id}}
                with start_span(
                    "worker.agent_run",
                    **{"agentos.run_id": ctx.run_id, "agentos.tenant_id": ctx.tenant_id},
                ):
                    if resume:
                        final = await app.ainvoke(None, cfg)
                    else:
                        final = await app.ainvoke(
                            {
                                "task": task,
                                "retrieved": [],
                                "seq": 1,
                                "tool_calls": 0,
                                "input_tokens": 0,
                                "output_tokens": 0,
                            },
                            cfg,
                        )
                result.update(final or {})
        except Exception as exc:  # surface as a run event, not a 500
            log.error("run.error", run_id=ctx.run_id, error=str(exc))
            error["message"] = str(exc)
        finally:
            await sink.close()

    await store.set_run_status(ctx.tenant_id, ctx.run_id, "running")
    if not resume:
        await store.append_action(
            tenant_id=ctx.tenant_id,
            run_id=ctx.run_id,
            seq=0,
            type="run_started",
            content={"task": task},
            trace_id=ctx.trace_id,
        )
        yield {"type": "run_started", "run_id": ctx.run_id}

    drive = asyncio.create_task(_drive())
    async for ev in sink.stream():
        yield ev
    await drive

    if error:
        # The run row carries terminal failure state (status + error); the checkpoint is left
        # intact so the run can be resumed from the last completed node. We deliberately do not
        # append a terminal action row here — its seq would collide with the node a resume
        # re-enters, and append is idempotent on (run_id, seq).
        await store.finalize_run(
            ctx.tenant_id, ctx.run_id, status="failed", error=error["message"]
        )
        yield {"type": "error", "run_id": ctx.run_id, "message": error["message"]}
        return

    seq = result.get("seq", 1)
    await store.finalize_run(
        ctx.tenant_id,
        ctx.run_id,
        status="completed",
        output=result.get("output", ""),
        input_tokens=result.get("input_tokens", 0),
        output_tokens=result.get("output_tokens", 0),
        tool_calls=result.get("tool_calls", 0),
        step_count=seq,
    )
    await store.append_action(
        tenant_id=ctx.tenant_id,
        run_id=ctx.run_id,
        seq=seq,
        type="run_completed",
        content={"output": result.get("output", "")},
        trace_id=ctx.trace_id,
    )
    yield {
        "type": "done",
        "run_id": ctx.run_id,
        "output": result.get("output", ""),
        "input_tokens": result.get("input_tokens", 0),
        "output_tokens": result.get("output_tokens", 0),
        "total_tokens": result.get("input_tokens", 0) + result.get("output_tokens", 0),
        "tool_calls": result.get("tool_calls", 0),
    }
