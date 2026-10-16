"""Control-plane audit logging (Phase 6, build task 1 — SOC 2 / full audit export).

Every mutation is recorded with who/what/which; the trail is exportable for a security review; and
a credential secret is **never** written to the audit log (only the fact one was stored).
"""

from __future__ import annotations

import pytest

from tests._helpers import headers, new_tenant_with_key


@pytest.mark.asyncio
async def test_mutations_are_audited_and_exportable(client):
    tid, key = await new_tenant_with_key("audit-1")
    h = headers(key)

    client.post("/v1/agents", headers=h, json={"name": "Audited"})
    client.post(
        "/v1/credentials",
        headers=h,
        json={"connector_key": "slack", "secret": "xoxb-TOP-SECRET-TOKEN", "name": "default"},
    )

    rows = client.get("/v1/audit", headers=h).json()
    actions = {r["action"] for r in rows}
    assert "agent.create" in actions
    assert "credential.store" in actions

    # Each row names the actor + how they authenticated.
    agent_row = next(r for r in rows if r["action"] == "agent.create")
    assert agent_row["actor_type"] == "api_key"
    assert agent_row["actor_role"] == "owner"


@pytest.mark.asyncio
async def test_credential_secret_never_appears_in_audit(client):
    tid, key = await new_tenant_with_key("audit-secret")
    h = headers(key)
    client.post(
        "/v1/credentials",
        headers=h,
        json={"connector_key": "slack", "secret": "xoxb-DO-NOT-LEAK", "name": "default"},
    )
    rows = client.get("/v1/audit", headers=h).json()
    blob = str(rows)
    assert "xoxb-DO-NOT-LEAK" not in blob


@pytest.mark.asyncio
async def test_audit_is_tenant_isolated(client):
    tid_a, key_a = await new_tenant_with_key("audit-a")
    tid_b, key_b = await new_tenant_with_key("audit-b")
    client.post("/v1/agents", headers=headers(key_a), json={"name": "A-only"})

    # B sees none of A's audit entries.
    rows_b = client.get("/v1/audit", headers=headers(key_b)).json()
    assert all(r["resource_type"] != "agent" for r in rows_b)
