"""Usage capture — write exactly one ``usage_event`` per billable action, idempotently.

Phase 0 only *captures* (``rated=False``); the rating engine and ledger arrive in Phase 3.
The idempotency key is the contract that makes rating exactly-once later: a retried model call
or a replayed event resolves to the same ``usage_event`` row.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_trace_id
from app.core.logging import get_logger
from app.metering.bus import get_bus
from app.models.usage_event import UsageEvent

log = get_logger(__name__)

USAGE_SUBJECT = "usage.captured"


@dataclass
class UsageRecord:
    tenant_id: str
    idempotency_key: str
    event_type: str  # "model_call" | "tool_call"
    provider: str
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    quantity: int = 1
    unit: str = "tokens"
    run_id: str | None = None
    agent_id: str | None = None
    trace_id: str | None = field(default=None)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


async def capture_usage(session: AsyncSession, rec: UsageRecord) -> UsageEvent:
    """Insert one usage_event, deduped on (tenant_id, idempotency_key). Returns the row.

    If an event with the same idempotency key already exists, the existing row is returned
    unchanged (exactly-once capture). Also publishes onto the bus for the downstream pipeline.
    """
    existing = (
        await session.execute(
            select(UsageEvent).where(
                UsageEvent.tenant_id == rec.tenant_id,
                UsageEvent.idempotency_key == rec.idempotency_key,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        log.info("usage.duplicate", idempotency_key=rec.idempotency_key, event_id=existing.id)
        return existing

    event = UsageEvent(
        tenant_id=rec.tenant_id,
        idempotency_key=rec.idempotency_key,
        event_type=rec.event_type,
        provider=rec.provider,
        model=rec.model,
        input_tokens=rec.input_tokens,
        output_tokens=rec.output_tokens,
        total_tokens=rec.total_tokens,
        quantity=rec.quantity,
        unit=rec.unit,
        run_id=rec.run_id,
        agent_id=rec.agent_id,
        trace_id=rec.trace_id or get_trace_id(),
    )
    session.add(event)
    await session.flush()  # assign id within the caller's transaction

    log.info(
        "usage.captured",
        event_id=event.id,
        event_type=event.event_type,
        provider=event.provider,
        model=event.model,
        total_tokens=event.total_tokens,
    )
    await get_bus().publish(
        USAGE_SUBJECT,
        {"tenant_id": event.tenant_id, "usage_event_id": event.id, "trace_id": event.trace_id},
    )
    return event
