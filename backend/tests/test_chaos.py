"""Chaos & recovery (Phase 5 exit criteria).

The exit bar: killing a worker or failing a provider must lose or double-count *no* usage. Two
scenarios here, on freshly-created tenants so the accounting is exact:

* **crash between capture and rating** — a usage event is captured (and logged to the outbox) but
  the process dies before it is rated. Replay repairs it **exactly once**: the first replay posts
  the one missing ledger entry; a second replay posts nothing. No lost usage, no double count.
* **provider failover mid-call** — the primary provider errors and the router fails over; the usage
  event is attributed to who actually served, and recording it twice (a retry) stays idempotent.

The worker-kill-then-resume case is covered end to end in test_run_resume.py.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.config import get_settings
from app.core.security import hash_api_key, key_prefix
from app.db.session import system_session, tenant_session
from app.metering.pipeline import record_usage
from app.metering.stream import replay_usage
from app.metering.usage import UsageRecord, capture_usage
from app.models.api_key import ApiKey
from app.models.ledger_entry import LedgerEntry
from app.models.tenant import Tenant
from app.models.user import User
from app.runtime.router import Candidate, ModelRouter
from app.services.ratecards import ensure_default_card
from tests.test_provider_router import PRICES, FailingProvider, StaticProvider


async def _new_tenant(slug: str) -> str:
    s = get_settings()
    async with system_session() as session:
        tenant = Tenant(slug=slug, name=slug)
        session.add(tenant)
        await session.flush()
        tid = tenant.id
        user = User(tenant_id=tid, email=f"{slug}@t.local", role="owner")
        session.add(user)
        await session.flush()
        session.add(
            ApiKey(
                tenant_id=tid,
                user_id=user.id,
                name="k",
                prefix=key_prefix(f"key-{slug}"),
                key_hash=hash_api_key(f"key-{slug}", pepper=s.api_key_pepper),
            )
        )
    await ensure_default_card(tid)
    return tid


async def _ledger_count(tid: str) -> int:
    async with tenant_session(tid) as session:
        return int(
            (
                await session.execute(
                    select(func.count()).where(LedgerEntry.tenant_id == tid)
                )
            ).scalar_one()
        )


async def test_crash_between_capture_and_rating_is_repaired_exactly_once(client):
    tid = await _new_tenant("chaos-gap")

    # Simulate the crash: capture (writes the usage event + the outbox row) but never rate.
    async with tenant_session(tid) as session:
        event = await capture_usage(
            session,
            UsageRecord(
                tenant_id=tid,
                idempotency_key="chaos:step1:model_call",
                event_type="model_call",
                provider="mock",
                model="gpt-4o-mini",
                input_tokens=1000,
                output_tokens=500,
                run_id="run-x",
                agent_id="agent-x",
            ),
        )
    assert event.rated is False
    assert await _ledger_count(tid) == 0  # nothing rated → a gap

    # Replay repairs the gap: exactly one ledger entry appears, and it counts as a repair.
    first = await replay_usage(tid)
    assert first.replayed == 1
    assert first.repaired == 1
    assert first.new_ledger_entries == 1
    assert first.exactly_once is True  # new entries == repaired
    assert await _ledger_count(tid) == 1

    # Replaying again changes nothing — no double count.
    second = await replay_usage(tid, from_offset=0)
    assert second.repaired == 0
    assert second.new_ledger_entries == 0
    assert second.exactly_once is True
    assert await _ledger_count(tid) == 1


async def test_failover_attributes_usage_and_stays_idempotent(client):
    tid = await _new_tenant("chaos-failover")

    # Primary (cheaper) is down; the router fails over to the backup and serves the call.
    router = ModelRouter(
        providers={"primary": FailingProvider("primary"), "backup": StaticProvider("backup", "ok")},
        candidates=[Candidate("primary", "cheap-model"), Candidate("backup", "pricey-model")],
        price_map=PRICES,
    )
    text = "".join([c.delta async for c in router.stream("hi") if c.delta])
    assert text == "ok"
    assert router.last_provider == "backup"

    rec = UsageRecord(
        tenant_id=tid,
        idempotency_key="failover:step1:model_call",
        event_type="model_call",
        provider=router.last_provider,  # attributed to who actually served
        model=router.last_model,
        input_tokens=100,
        output_tokens=100,
        run_id="run-f",
        agent_id="agent-f",
    )
    async with tenant_session(tid) as session:
        ev1 = await record_usage(session, rec)
    # A retry of the same step (same idempotency key) must not double-charge.
    async with tenant_session(tid) as session:
        ev2 = await record_usage(session, rec)

    assert ev1.id == ev2.id
    assert ev1.provider == "backup"
    assert await _ledger_count(tid) == 1  # exactly one charge despite the failover + retry
