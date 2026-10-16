"""Fraud & abuse controls (Phase 6, build task 3): velocity limits, holds, anomaly-driven holds.

A tripped velocity limit places a hold and raises; a held tenant's billable work is refused until
an operator releases it; a recent critical anomaly can be promoted to a hold by the operator scan.
"""

from __future__ import annotations

import pytest

from app.core.errors import TenantHeldError, VelocityError
from app.db.session import tenant_session
from app.fraud import controls
from app.metering.anomaly import raise_alert
from tests._helpers import headers, new_tenant_with_key


@pytest.mark.asyncio
async def test_velocity_breach_places_hold_and_blocks(client):
    tid, _ = await new_tenant_with_key("fraud-velocity")
    controls._reset_counters()

    # Under the limit: fine. Over it: raises *and* a hold is now active.
    await controls.check_velocity(tid, "run", limit=2, window_s=60)
    await controls.check_velocity(tid, "run", limit=2, window_s=60)
    with pytest.raises(VelocityError):
        await controls.check_velocity(tid, "run", limit=2, window_s=60)

    assert await controls.active_hold(tid) is not None
    with pytest.raises(TenantHeldError):
        await controls.assert_not_held(tid)


@pytest.mark.asyncio
async def test_release_unblocks(client):
    tid, _ = await new_tenant_with_key("fraud-release")
    hold = await controls.place_hold(tid, kind="manual", reason="testing")
    with pytest.raises(TenantHeldError):
        await controls.assert_not_held(tid)

    released = await controls.release_hold(tid, hold.id, released_by="op")
    assert released.active is False and released.released_at is not None
    await controls.assert_not_held(tid)  # no longer raises


@pytest.mark.asyncio
async def test_anomaly_scan_promotes_runaway_to_hold(client):
    tid, _ = await new_tenant_with_key("fraud-anomaly")
    async with tenant_session(tid) as session:
        await raise_alert(
            session,
            tenant_id=tid,
            kind="runaway_loop",
            severity="critical",
            message="runaway",
            run_id="r-1",
            dedupe_per_run=False,
        )
    hold = await controls.evaluate_anomaly_holds(tid)
    assert hold is not None and hold.kind == "anomaly" and hold.active is True


@pytest.mark.asyncio
async def test_held_tenant_cannot_trigger_a_run_via_api(client):
    tid, key = await new_tenant_with_key("fraud-run-block")
    await controls.place_hold(tid, kind="manual", reason="under review")
    h = headers(key)
    agent = client.post("/v1/agents", headers=h, json={"name": "Blocked"}).json()
    r = client.post(f"/v1/agents/{agent['id']}/runs", headers=h, json={"task": "hi"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "tenant_held"


@pytest.mark.asyncio
async def test_hold_admin_endpoints(client):
    tid, key = await new_tenant_with_key("fraud-admin")
    h = headers(key)
    placed = client.post("/v1/admin/holds", headers=h, json={"reason": "manual review"})
    assert placed.status_code == 201
    hold_id = placed.json()["id"]

    listed = client.get("/v1/admin/holds?active_only=true", headers=h).json()
    assert any(x["id"] == hold_id for x in listed)

    rel = client.post(f"/v1/admin/holds/{hold_id}/release", headers=h)
    assert rel.status_code == 200 and rel.json()["active"] is False


@pytest.mark.asyncio
async def test_hold_requires_admin_role(client):
    tid, key = await new_tenant_with_key("fraud-rbac", role="member")
    r = client.post("/v1/admin/holds", headers=headers(key), json={"reason": "x"})
    assert r.status_code == 403
