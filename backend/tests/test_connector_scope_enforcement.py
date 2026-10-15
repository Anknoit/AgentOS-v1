"""The ConnectorBroker enforces scope at call time: granted calls run, ungranted ones are denied.

This is the Phase 2 security invariant in isolation — the end-to-end agent version lives in
``test_connected_support_desk.py``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.connectors.broker import ConnectorBroker, ConnectorGrants
from app.core.errors import ScopeDeniedError
from app.db.session import system_session, tenant_session
from app.models.action_log import ActionLog
from app.models.tenant import Tenant
from app.models.usage_event import UsageEvent
from app.services import credentials as vault


async def _tenant_id() -> str:
    async with system_session() as s:
        return (await s.execute(select(Tenant).limit(1))).scalar_one().id


def _broker(tid: str, run_id: str, bindings: dict) -> ConnectorBroker:
    return ConnectorBroker(
        tenant_id=tid,
        run_id=run_id,
        trace_id="trace-scope-test",
        grants=ConnectorGrants.from_bindings(bindings),
    )


@pytest.mark.asyncio
async def test_granted_call_runs_meters_and_audits(client):
    tid = await _tenant_id()
    await vault.put_credential(tid, connector_key="crm", secret="k", provider_meta={})
    broker = _broker(tid, "scope-run-ok", {"crm": {"scopes": ["crm:read"]}})

    call = await broker.call("crm.search_contacts", {"query": "dana"}, seq=1)
    assert call.connector_key == "crm"
    assert call.usage_event_id  # metered
    assert call.output["results"]

    async with tenant_session(tid) as s:
        action = (
            await s.execute(
                select(ActionLog).where(
                    ActionLog.run_id == "scope-run-ok", ActionLog.seq == 1
                )
            )
        ).scalar_one()
        assert action.type == "connector_call"
        assert action.content["outcome"] == "ok"
        assert action.trace_id == "trace-scope-test"
        usage = (
            await s.execute(
                select(UsageEvent).where(UsageEvent.run_id == "scope-run-ok")
            )
        ).scalars().all()
    assert [u.event_type for u in usage] == ["connector_call"]


@pytest.mark.asyncio
async def test_ungranted_scope_is_denied_and_logged(client):
    tid = await _tenant_id()
    await vault.put_credential(tid, connector_key="crm", secret="k", provider_meta={})
    # grant read only — writing a ticket needs crm:write
    broker = _broker(tid, "scope-run-deny", {"crm": {"scopes": ["crm:read"]}})

    with pytest.raises(ScopeDeniedError):
        await broker.call("crm.create_ticket", {"subject": "refund"}, seq=1)

    async with tenant_session(tid) as s:
        action = (
            await s.execute(
                select(ActionLog).where(
                    ActionLog.run_id == "scope-run-deny", ActionLog.seq == 1
                )
            )
        ).scalar_one()
        assert action.content["outcome"] == "denied"
        assert action.content["scope"] == "crm:write"
        # denial is attributable and records what WAS granted
        assert action.content["granted_scopes"] == ["crm:read"]
        # a denied call does no work, so nothing is metered
        usage = (
            await s.execute(
                select(UsageEvent).where(UsageEvent.run_id == "scope-run-deny")
            )
        ).scalars().all()
    assert usage == []


@pytest.mark.asyncio
async def test_unbound_connector_is_denied(client):
    tid = await _tenant_id()
    broker = _broker(tid, "scope-run-unbound", {})  # nothing granted at all
    with pytest.raises(ScopeDeniedError):
        await broker.call("slack.post_message", {"channel": "#x", "text": "hi"}, seq=1)
