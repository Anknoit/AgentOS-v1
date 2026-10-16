"""Compliance & self-hosted controls (Phase 6, build tasks 1 & 5).

The security-posture report (the review artifact), the retention purge (operational rows age out;
the money ledger never does), and self-hosted single-tenant pinning (hard isolation on-prem).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings
from app.db.session import tenant_session
from app.models.ledger_entry import LedgerEntry
from app.models.run import Run
from tests._helpers import headers, new_tenant_with_key


@pytest.mark.asyncio
async def test_posture_report_shape(client, auth_headers):
    r = client.get("/v1/compliance/report", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_isolation"].startswith("app-scoped") or "rls" in body["tenant_isolation"]
    assert body["encryption"]["credentials_at_rest"] == "per-tenant-fernet-hkdf"
    assert set(body["identity"]) >= {"rbac_enabled", "sso_mode", "api_keys"}
    assert "review_ready" in body


@pytest.mark.asyncio
async def test_retention_purges_old_runs_but_never_the_ledger(client):
    tid, _ = await new_tenant_with_key("retention-1")
    old = datetime.now(timezone.utc) - timedelta(days=40)
    async with tenant_session(tid) as session:
        session.add(
            Run(tenant_id=tid, task="old", status="completed", created_at=old, updated_at=old)
        )
        session.add(
            LedgerEntry(
                tenant_id=tid, entry_type="usage", ref="r:old", event_type="model_call",
                provider="mock", cost_nanos=10, price_nanos=20, created_at=old, updated_at=old,
            )
        )

    s = get_settings()
    prev = s.data_retention_days
    s.data_retention_days = 30
    try:
        from app.compliance.retention import purge_tenant

        deleted = await purge_tenant(tid)
    finally:
        s.data_retention_days = prev

    assert deleted.get("run", 0) >= 1
    # The money ledger is untouched by retention.
    async with tenant_session(tid) as session:
        from sqlalchemy import func, select

        n = (
            await session.execute(
                select(func.count()).select_from(LedgerEntry).where(LedgerEntry.tenant_id == tid)
            )
        ).scalar_one()
        assert n == 1


@pytest.mark.asyncio
async def test_retention_disabled_is_a_noop(client):
    tid, _ = await new_tenant_with_key("retention-off")
    assert get_settings().data_retention_days == 0
    from app.compliance.retention import purge_tenant

    assert await purge_tenant(tid) == {}


@pytest.mark.asyncio
async def test_self_hosted_single_tenant_pin(client):
    tid_x, key_x = await new_tenant_with_key("selfhost-x")
    tid_y, key_y = await new_tenant_with_key("selfhost-y")
    s = get_settings()
    prev = s.single_tenant_id
    s.single_tenant_id = tid_x
    try:
        # The pinned tenant authenticates; any other tenant's key is refused.
        assert client.get("/v1/whoami", headers=headers(key_x)).status_code == 200
        r = client.get("/v1/whoami", headers=headers(key_y))
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "wrong_tenant"
    finally:
        s.single_tenant_id = prev
