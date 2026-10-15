"""Durable metering stream + exactly-once replay (Phase 5, build tasks 2 & 4).

A run's billable actions land on the durable event log (the transactional outbox). Replaying that
stream through the idempotent pipeline must post *nothing* new for already-rated events — the
exactly-once guarantee the whole moat rests on, now proven under an explicit replay rather than
only an incidental resume. The replay-repairs-a-gap half is proven in test_chaos.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.config import get_settings
from app.core.security import hash_api_key, key_prefix
from app.db.session import system_session, tenant_session
from app.metering.pipeline import record_usage
from app.metering.stream import replay_usage, stream_depth
from app.metering.usage import UsageRecord
from app.models.api_key import ApiKey
from app.models.ledger_entry import LedgerEntry
from app.models.tenant import Tenant
from app.models.user import User
from app.services.ratecards import ensure_default_card


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


async def _record(tid: str, key: str) -> None:
    async with tenant_session(tid) as session:
        await record_usage(
            session,
            UsageRecord(
                tenant_id=tid,
                idempotency_key=key,
                event_type="model_call",
                provider="mock",
                model="gpt-4o-mini",
                input_tokens=1000,
                output_tokens=500,
                run_id="run-1",
                agent_id="agent-1",
            ),
        )


async def _ledger_count(tid: str) -> int:
    async with tenant_session(tid) as session:
        return int(
            (
                await session.execute(
                    select(func.count()).where(LedgerEntry.tenant_id == tid)
                )
            ).scalar_one()
        )


def test_run_lands_on_the_durable_stream(client, auth_headers):
    """A real run (on the shared dev tenant) advances the durable stream head."""
    before = client.get("/v1/ops/stream", headers=auth_headers).json()
    agent = client.post(
        "/v1/agents",
        headers=auth_headers,
        json={"name": "StreamDesk", "template": "support_desk"},
    ).json()
    run = client.post(
        f"/v1/agents/{agent['id']}/runs",
        headers=auth_headers,
        json={"task": "How do I reset my password?"},
    ).json()
    assert run["status"] == "completed", run

    after = client.get("/v1/ops/stream", headers=auth_headers).json()
    assert after["head_offset"] > before["head_offset"]
    assert after["event_count"] >= before["event_count"] + 2  # a tool_call and a model_call


async def test_replay_of_rated_stream_changes_nothing(client):
    """On a controlled stream of already-rated events, replay is a perfect no-op (exactly-once)."""
    tid = await _new_tenant("replay-xo")
    await _record(tid, "r:step1:model_call")
    await _record(tid, "r:step2:model_call")
    assert await _ledger_count(tid) == 2

    health = await stream_depth(tid)
    assert health.event_count == 2
    assert health.lag == 2  # nothing consumed yet

    result = await replay_usage(tid)
    assert result.replayed == 2
    assert result.repaired == 0
    assert result.new_ledger_entries == 0
    assert result.balance_delta == 0
    assert result.exactly_once is True
    assert await _ledger_count(tid) == 2

    # Committing the offset drains the lag; a second replay from scratch still changes nothing.
    assert (await stream_depth(tid)).lag == 0
    again = await replay_usage(tid, from_offset=0)
    assert again.new_ledger_entries == 0
    assert again.exactly_once is True
