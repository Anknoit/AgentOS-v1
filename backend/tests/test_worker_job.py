"""The Arq worker task runs the loop and persists usage — without Redis.

This proves the worker function (ADR-0001) executes a run off the request path. Enqueueing
over a live Redis is exercised in the compose/CI Postgres+Redis profile, not here.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db.session import system_session, tenant_session
from app.models.tenant import Tenant
from app.models.usage_event import UsageEvent
from app.runtime.queue import execute_run_job


@pytest.mark.asyncio
async def test_execute_run_job(client):
    async with system_session() as s:
        tenant_id = (await s.execute(select(Tenant).limit(1))).scalar_one().id

    payload = {
        "tenant_id": tenant_id,
        "task": "worker task",
        "run_id": "worker-run-1",
        "trace_id": "trace-worker-1",
        "traceparent": {},
    }
    result = await execute_run_job({"settings": get_settings()}, payload)

    assert result["run_id"] == "worker-run-1"
    assert result["result"]["type"] == "done"

    async with tenant_session(tenant_id) as s:
        ev = (
            await s.execute(select(UsageEvent).where(UsageEvent.run_id == "worker-run-1"))
        ).scalar_one()
    assert ev.trace_id == "trace-worker-1"
    assert ev.total_tokens > 0
