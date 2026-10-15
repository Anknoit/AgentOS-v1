"""Exactly-once capture: the same idempotency key never writes two usage_events."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.db.session import tenant_session
from app.metering.usage import UsageRecord, capture_usage
from app.models.usage_event import UsageEvent


@pytest.mark.asyncio
async def test_capture_is_idempotent(client):
    # `client` fixture ensures the app (engine + schema + seed) is initialised.
    tenant_id = await _some_tenant_id()
    rec = UsageRecord(
        tenant_id=tenant_id,
        idempotency_key="run-xyz:model_call:0",
        event_type="model_call",
        provider="mock",
        model="gpt-4o-mini",
        input_tokens=10,
        output_tokens=20,
    )
    async with tenant_session(tenant_id) as s:
        first = await capture_usage(s, rec)
    async with tenant_session(tenant_id) as s:
        second = await capture_usage(s, rec)

    assert first.id == second.id
    async with tenant_session(tenant_id) as s:
        count = (
            await s.execute(
                select(func.count())
                .select_from(UsageEvent)
                .where(UsageEvent.idempotency_key == rec.idempotency_key)
            )
        ).scalar_one()
    assert count == 1


async def _some_tenant_id() -> str:
    from app.db.session import system_session
    from app.models.tenant import Tenant

    async with system_session() as s:
        return (await s.execute(select(Tenant).limit(1))).scalar_one().id
