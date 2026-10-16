"""RBAC (Phase 6, build task 2) — a scoped role is denied actions outside its grants.

The Phase 6 exit criterion requires onboarding with *scoped roles*. These tests prove the gate: an
``auditor`` key can read but not write; a ``member`` key can build agents but not touch billing or
members; the ``owner`` key (what everything defaulted to) still does everything.
"""

from __future__ import annotations

import pytest

from tests._helpers import headers, new_tenant_with_key


@pytest.mark.asyncio
async def test_auditor_can_read_but_not_write(client):
    tid, key = await new_tenant_with_key("rbac-auditor", role="auditor")
    h = headers(key)

    # Reads are allowed.
    assert client.get("/v1/agents", headers=h).status_code == 200
    assert client.get("/v1/audit", headers=h).status_code == 200

    # Writes are forbidden with a stable code.
    r = client.post("/v1/agents", headers=h, json={"name": "Nope"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


@pytest.mark.asyncio
async def test_member_can_build_agents_but_not_bill_or_manage_members(client):
    tid, key = await new_tenant_with_key("rbac-member", role="member")
    h = headers(key)

    # A member builds and runs agents.
    created = client.post("/v1/agents", headers=h, json={"name": "Builder"})
    assert created.status_code == 201

    # ...but cannot top up the wallet (billing:write) or manage members (members:write).
    topup = client.post("/v1/billing/topups", headers=h, json={"amount_usd": "10"})
    assert topup.status_code == 403
    assert client.get("/v1/members", headers=h).status_code == 403
    assert (
        client.post("/v1/members", headers=h, json={"email": "x@y.z"}).status_code == 403
    )


@pytest.mark.asyncio
async def test_owner_has_everything(client):
    tid, key = await new_tenant_with_key("rbac-owner", role="owner")
    h = headers(key)
    assert client.get("/v1/members", headers=h).status_code == 200
    assert client.post("/v1/agents", headers=h, json={"name": "Owned"}).status_code == 201
    assert client.get("/v1/compliance/report", headers=h).status_code == 200


@pytest.mark.asyncio
async def test_roles_matrix_is_discoverable(client, auth_headers):
    r = client.get("/v1/auth/roles", headers=auth_headers)
    assert r.status_code == 200
    roles = r.json()["roles"]
    assert "owner" in roles and "auditor" in roles
    # The owner role grants a superset of the auditor role.
    assert set(roles["auditor"]).issubset(set(roles["owner"]))
