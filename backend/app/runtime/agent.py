"""Phase 0 agent-loop spike.

A trivial agent loop: take a task, stream a model response to the client, then capture exactly
one ``usage_event`` for the model call. It runs inside a ``worker.agent_loop`` span so, together
with the API request span and the client's trace header, one trace spans client -> API ->
worker -> provider call (the Phase 0 exit criterion).

This is deliberately thin — Phase 1 replaces it with a LangGraph kernel, checkpointing, and an
``action_log``. The *shape* (stream events out, capture metered usage) is what Phase 1 keeps.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from app.config.settings import Settings
from app.core.logging import get_logger
from app.core.tracing import start_span
from app.db.session import tenant_session
from app.metering.usage import UsageRecord, capture_usage
from app.runtime.providers import get_provider

log = get_logger(__name__)


async def run_agent_loop(
    *,
    tenant_id: str,
    task: str,
    settings: Settings,
    run_id: str | None = None,
    agent_id: str | None = None,
) -> AsyncIterator[dict]:
    """Yield run events: ``{"type": "token"|"usage"|"done"|"error", ...}``."""
    run_id = run_id or uuid.uuid4().hex
    provider = get_provider(settings)

    with start_span(
        "worker.agent_loop",
        **{"agentos.run_id": run_id, "agentos.tenant_id": tenant_id, "llm.provider": provider.name},
    ):
        log.info("run.start", run_id=run_id, provider=provider.name, model=settings.llm_model)
        yield {"type": "run_started", "run_id": run_id, "provider": provider.name}

        input_tokens = output_tokens = 0
        try:
            with start_span("provider.chat.stream", **{"llm.model": settings.llm_model}):
                async for chunk in provider.stream(task, model=settings.llm_model):
                    if chunk.delta:
                        yield {"type": "token", "run_id": run_id, "text": chunk.delta}
                    if chunk.done and chunk.usage is not None:
                        input_tokens = chunk.usage.input_tokens
                        output_tokens = chunk.usage.output_tokens
        except Exception as exc:  # surface provider failures as a run event, not a 500
            log.error("run.error", run_id=run_id, error=str(exc))
            yield {"type": "error", "run_id": run_id, "message": str(exc)}
            return

        # Capture exactly one usage_event for this model call (idempotent on the key).
        with start_span("metering.capture_usage"):
            async with tenant_session(tenant_id) as session:
                event = await capture_usage(
                    session,
                    UsageRecord(
                        tenant_id=tenant_id,
                        idempotency_key=f"{run_id}:model_call:0",
                        event_type="model_call",
                        provider=provider.name,
                        model=settings.llm_model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        run_id=run_id,
                        agent_id=agent_id,
                    ),
                )
                usage_event_id = event.id

        yield {
            "type": "usage",
            "run_id": run_id,
            "usage_event_id": usage_event_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        log.info("run.done", run_id=run_id, usage_event_id=usage_event_id)
        yield {"type": "done", "run_id": run_id, "usage_event_id": usage_event_id}
