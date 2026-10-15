"""The metering pipeline — capture → rate → ledger → wallet → anomaly, exactly once.

This is the single entry point the runtime uses to record a billable action. In v0 it runs
**inline and co-transactional** with usage capture: on one Postgres, pricing an event in the same
transaction that captures it is the simplest way to guarantee exactly-once rating — there is no
window where an event is captured but unrated, and no dropped async message can double- or
under-count. The event bus still carries ``usage.captured`` (published by ``capture_usage``) as
the decoupling seam for async consumers; at Kafka scale (Phase 5) the rating step moves to an
out-of-process consumer behind that same subject (ADR-0009).

Exactly-once rests on two deterministic keys: ``usage_event`` dedupes on
``(tenant_id, idempotency_key)`` and ``ledger_entry`` dedupes on ``(tenant_id, usage_event_id)``.
A replayed step (same idempotency key after a resume) finds the usage event already rated and
returns it untouched — no second ledger entry, no double debit.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.tracing import start_span
from app.metering.anomaly import check_event
from app.metering.rating import RateCardData, rate_event
from app.metering.usage import UsageRecord, capture_usage
from app.models.ledger_entry import LedgerEntry
from app.models.usage_event import UsageEvent
from app.models.wallet import Wallet
from app.services import ratecards

log = get_logger(__name__)


async def record_usage(
    session: AsyncSession, rec: UsageRecord, *, card: RateCardData | None = None
) -> UsageEvent:
    """Capture, rate, post to the ledger, update the wallet, and screen for anomalies.

    Drop-in replacement for :func:`capture_usage` in the runtime: same signature and return, but
    the event is priced and posted before this returns. Idempotent — a replayed event is returned
    already rated, with no second ledger write.
    """
    event = await capture_usage(session, rec)
    if event.rated:
        return event

    card = card or await ratecards.get_active_card(rec.tenant_id)
    rated = rate_event(
        card,
        event_type=event.event_type,
        model=event.model,
        provider=event.provider,
        input_tokens=event.input_tokens,
        output_tokens=event.output_tokens,
        quantity=event.quantity,
        connector_key=event.provider if event.event_type == "connector_call" else None,
        tool_name=event.model if event.event_type == "tool_call" else None,
    )

    with start_span("metering.rate_and_post", **{"usage.kind": event.event_type}):
        await _post_ledger(session, event, rated, card)
        await _apply_to_wallet(session, rec.tenant_id, rated.price_nanos)
        event.rated = True
        await session.flush()
        await check_event(
            session,
            tenant_id=rec.tenant_id,
            run_id=event.run_id,
            agent_id=event.agent_id,
            price_nanos=rated.price_nanos,
        )

    log.info(
        "usage.rated",
        event_id=event.id,
        event_type=event.event_type,
        cost_nanos=rated.cost_nanos,
        price_nanos=rated.price_nanos,
    )
    return event


async def _post_ledger(session: AsyncSession, event: UsageEvent, rated, card) -> None:
    existing = (
        await session.execute(
            select(LedgerEntry).where(
                LedgerEntry.tenant_id == event.tenant_id,
                LedgerEntry.usage_event_id == event.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:  # already posted (defensive — rated flag normally short-circuits)
        return
    session.add(
        LedgerEntry(
            tenant_id=event.tenant_id,
            entry_type="usage",
            usage_event_id=event.id,
            run_id=event.run_id,
            agent_id=event.agent_id,
            event_type=event.event_type,
            provider=event.provider,
            model=event.model,
            quantity=event.quantity,
            cost_nanos=rated.cost_nanos,
            price_nanos=rated.price_nanos,
            currency=rated.currency,
            rate_card_id=card.card_id,
            trace_id=event.trace_id,
            detail=rated.detail,
        )
    )
    await session.flush()


async def _apply_to_wallet(session: AsyncSession, tenant_id: str, price_nanos: int) -> None:
    """Debit the wallet projection. Get-or-create the tenant's single wallet."""
    wallet = (
        await session.execute(select(Wallet).where(Wallet.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if wallet is None:
        wallet = Wallet(tenant_id=tenant_id, currency="USD", balance_nanos=0)
        session.add(wallet)
        await session.flush()
    wallet.balance_nanos = wallet.balance_nanos - price_nanos
