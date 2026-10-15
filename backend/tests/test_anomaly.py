"""Simple anomaly detection on the metering path — runaway loops raise an alert."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.session import system_session, tenant_session
from app.metering.anomaly import RUNAWAY_STEP_THRESHOLD
from app.metering.pipeline import record_usage
from app.metering.usage import UsageRecord
from app.models.alert import Alert
from app.models.tenant import Tenant


async def _tenant_id() -> str:
    async with system_session() as s:
        return (await s.execute(select(Tenant).limit(1))).scalar_one().id


@pytest.mark.asyncio
async def test_runaway_loop_raises_one_alert(client):
    tenant_id = await _tenant_id()
    run_id = "runaway-run"
    # Bill well past the runaway threshold on a single run.
    for i in range(RUNAWAY_STEP_THRESHOLD + 5):
        async with tenant_session(tenant_id) as s:
            await record_usage(
                s,
                UsageRecord(
                    tenant_id=tenant_id,
                    idempotency_key=f"{run_id}:step{i}:tool:loop",
                    event_type="tool_call",
                    provider="tool",
                    model="loop",
                    run_id=run_id,
                ),
            )

    async with tenant_session(tenant_id) as s:
        alerts = (
            await s.execute(
                select(Alert).where(Alert.run_id == run_id, Alert.kind == "runaway_loop")
            )
        ).scalars().all()
    # Detected, and deduped to exactly one alert per run (not one per step).
    assert len(alerts) == 1
    assert alerts[0].severity == "critical"
    assert alerts[0].context["threshold"] == RUNAWAY_STEP_THRESHOLD
