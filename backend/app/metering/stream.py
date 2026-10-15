"""The durable-stream consumer and replay tool (Phase 5, build tasks 2 & 4).

The durable :class:`~app.models.event_log.EventLog` is the replayable record of every published
event. This module is how work is read back off it:

* :func:`append_event` — write one event to the log (used by :class:`~app.metering.bus.DurableBus`);
* :func:`stream_depth` / :func:`consumer_lag` — ingestion health (how far a consumer trails head);
* :func:`replay_usage` — re-feed a range of the ``usage.captured`` stream through the **idempotent**
  metering pipeline. On a healthy stream this posts nothing (the exactly-once proof); on a stream
  with a captured-but-unrated gap (a crash between capture and rating) it repairs the gap exactly
  once. Either way it commits the consumer offset so a later replay resumes, not restarts.

At Kafka scale the same consumer runs out-of-process behind the ``usage.captured`` subject; the
offset/commit semantics here mirror a Kafka consumer group's, so the logic ports unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select

from app.core.logging import get_logger
from app.db.session import tenant_session
from app.metering.pipeline import rate_existing_event
from app.metering.usage import USAGE_SUBJECT
from app.models.consumer_offset import ConsumerOffset
from app.models.event_log import EventLog
from app.models.ledger_entry import LedgerEntry
from app.models.usage_event import UsageEvent
from app.models.wallet import Wallet

log = get_logger(__name__)

RATING_CONSUMER = "rating"


async def append_event(
    *, tenant_id: str, subject: str, payload: dict, trace_id: str | None = None
) -> int:
    """Append one event to the durable log; returns its assigned offset."""
    async with tenant_session(tenant_id) as session:
        row = EventLog(
            tenant_id=tenant_id, subject=subject, payload=payload, trace_id=trace_id
        )
        session.add(row)
        await session.flush()
        return int(row.offset)


@dataclass
class StreamHealth:
    tenant_id: str
    head_offset: int  # highest offset in the log for this tenant (0 if empty), a resume cursor
    event_count: int  # total events logged for this tenant
    committed_offset: int  # how far the consumer has processed (a global-offset value)
    lag: int  # number of this tenant's events not yet consumed (offset > committed)


async def stream_depth(tenant_id: str, *, consumer: str = RATING_CONSUMER) -> StreamHealth:
    """Ingestion health for a tenant: log head, total events, consumer offset, and lag.

    Offsets are a global sequence, so a tenant's rows are sparse in it; lag is therefore the *count*
    of this tenant's events past the committed offset, not an offset subtraction.
    """
    async with tenant_session(tenant_id) as session:
        head, count = (
            await session.execute(
                select(
                    func.coalesce(func.max(EventLog.offset), 0),
                    func.count(),
                ).where(EventLog.tenant_id == tenant_id)
            )
        ).one()
        committed = await _committed_offset(session, tenant_id, consumer)
        lag = int(
            (
                await session.execute(
                    select(func.count()).where(
                        EventLog.tenant_id == tenant_id, EventLog.offset > committed
                    )
                )
            ).scalar_one()
        )
    return StreamHealth(
        tenant_id=tenant_id,
        head_offset=int(head),
        event_count=int(count),
        committed_offset=committed,
        lag=lag,
    )


async def _committed_offset(session, tenant_id: str, consumer: str) -> int:
    row = (
        await session.execute(
            select(ConsumerOffset).where(
                ConsumerOffset.tenant_id == tenant_id, ConsumerOffset.consumer == consumer
            )
        )
    ).scalar_one_or_none()
    return int(row.committed_offset) if row is not None else 0


async def _commit_offset(session, tenant_id: str, consumer: str, offset: int) -> None:
    row = (
        await session.execute(
            select(ConsumerOffset).where(
                ConsumerOffset.tenant_id == tenant_id, ConsumerOffset.consumer == consumer
            )
        )
    ).scalar_one_or_none()
    if row is None:
        session.add(
            ConsumerOffset(tenant_id=tenant_id, consumer=consumer, committed_offset=offset)
        )
    else:
        row.committed_offset = max(row.committed_offset, offset)
    await session.flush()


@dataclass
class ReplayResult:
    tenant_id: str
    from_offset: int
    to_offset: int
    replayed: int  # usage events re-read
    repaired: int  # events that were unrated and got a ledger entry on replay
    ledger_before: int
    ledger_after: int
    balance_before: int
    balance_after: int

    @property
    def new_ledger_entries(self) -> int:
        return self.ledger_after - self.ledger_before

    @property
    def balance_delta(self) -> int:
        return self.balance_after - self.balance_before

    @property
    def exactly_once(self) -> bool:
        """A replay that only *repaired* gaps is still exactly-once: new entries == repaired."""
        return self.new_ledger_entries == self.repaired


async def replay_usage(
    tenant_id: str,
    *,
    from_offset: int | None = None,
    limit: int = 10_000,
    consumer: str = RATING_CONSUMER,
    commit: bool = True,
) -> ReplayResult:
    """Replay the tenant's ``usage.captured`` stream through the idempotent pipeline.

    Reads events after ``from_offset`` (default: the consumer's committed offset) and re-rates each
    referenced usage event. Already-rated events are no-ops, so a healthy stream yields zero new
    ledger entries and zero balance change; captured-but-unrated gaps are repaired exactly once.
    Commits the consumer offset at the end unless ``commit=False`` (a dry run).
    """
    async with tenant_session(tenant_id) as session:
        ledger_before = await _ledger_count(session, tenant_id)
        balance_before = await _balance(session, tenant_id)
        start = (
            from_offset
            if from_offset is not None
            else await _committed_offset(session, tenant_id, consumer)
        )

        rows = (
            await session.execute(
                select(EventLog)
                .where(
                    EventLog.tenant_id == tenant_id,
                    EventLog.subject == USAGE_SUBJECT,
                    EventLog.offset > start,
                )
                .order_by(EventLog.offset.asc())
                .limit(limit)
            )
        ).scalars().all()

        replayed = 0
        repaired = 0
        last_offset = start
        for row in rows:
            last_offset = int(row.offset)
            event_id = (row.payload or {}).get("usage_event_id")
            if not event_id:
                continue
            event = (
                await session.execute(
                    select(UsageEvent).where(
                        UsageEvent.tenant_id == tenant_id, UsageEvent.id == event_id
                    )
                )
            ).scalar_one_or_none()
            if event is None:  # logged but its usage event rolled back — nothing to replay
                continue
            replayed += 1
            if await rate_existing_event(session, event):
                repaired += 1

        if commit and rows:
            await _commit_offset(session, tenant_id, consumer, last_offset)

        ledger_after = await _ledger_count(session, tenant_id)
        balance_after = await _balance(session, tenant_id)

    result = ReplayResult(
        tenant_id=tenant_id,
        from_offset=start,
        to_offset=last_offset,
        replayed=replayed,
        repaired=repaired,
        ledger_before=ledger_before,
        ledger_after=ledger_after,
        balance_before=balance_before,
        balance_after=balance_after,
    )
    log.info(
        "stream.replayed",
        tenant_id=tenant_id,
        replayed=replayed,
        repaired=repaired,
        new_ledger_entries=result.new_ledger_entries,
        exactly_once=result.exactly_once,
    )
    return result


async def _ledger_count(session, tenant_id: str) -> int:
    return int(
        (
            await session.execute(
                select(func.count()).where(LedgerEntry.tenant_id == tenant_id)
            )
        ).scalar_one()
    )


async def _balance(session, tenant_id: str) -> int:
    wallet = (
        await session.execute(select(Wallet).where(Wallet.tenant_id == tenant_id))
    ).scalar_one_or_none()
    return int(wallet.balance_nanos) if wallet is not None else 0
