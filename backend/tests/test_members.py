"""Member + scoped-API-key management (Phase 6, RBAC onboarding)."""

from __future__ import annotations

import pytest

from tests._helpers import headers, new_tenant_with_key


@pytest.mark.asyncio
async def test_member_lifecycle(client):
    tid, key = await new_tenant_with_key("members-1")
    h = headers(key)

    created = client.post("/v1/members", headers=h, json={"email": "eng@acme.co", "role": "member"})
    assert created.status_code == 201
    uid = created.json()["id"]
    assert created.json()["role"] == "member"

    promoted = client.patch(f"/v1/members/{uid}", headers=h, json={"role": "admin"})
    assert promoted.status_code == 200 and promoted.json()["role"] == "admin"

    listed = client.get("/v1/members", headers=h).json()
    assert any(m["id"] == uid for m in listed)

    assert client.delete(f"/v1/members/{uid}", headers=h).status_code == 204


@pytest.mark.asyncio
async def test_unknown_role_is_rejected(client):
    tid, key = await new_tenant_with_key("members-badrole")
    r = client.post(
        "/v1/members", headers=headers(key), json={"email": "x@y.z", "role": "superuser"}
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_scoped_api_key_authenticates_with_its_role(client):
    tid, key = await new_tenant_with_key("members-keys")
    h = headers(key)

    minted = client.post("/v1/api-keys", headers=h, json={"name": "ci", "role": "auditor"})
    assert minted.status_code == 201
    raw = minted.json()["key"]  # shown exactly once
    assert raw.startswith("ak_")

    # The minted key authenticates as an auditor: reads ok, writes forbidden.
    kh = headers(raw)
    who = client.get("/v1/whoami", headers=kh).json()
    assert who["role"] == "auditor" and who["tenant_id"] == tid
    assert client.post("/v1/agents", headers=kh, json={"name": "No"}).status_code == 403

    # Revoke it: it no longer authenticates.
    key_id = minted.json()["id"]
    assert client.delete(f"/v1/api-keys/{key_id}", headers=h).status_code == 204
    assert client.get("/v1/whoami", headers=kh).status_code == 401


@pytest.mark.asyncio
async def test_api_key_plaintext_never_listed(client):
    tid, key = await new_tenant_with_key("members-nolist")
    h = headers(key)
    minted = client.post("/v1/api-keys", headers=h, json={"name": "x", "role": "member"})
    raw = minted.json()["key"]
    listed = client.get("/v1/api-keys", headers=h).json()
    assert all("key" not in row or row.get("key") is None for row in listed)
    assert raw not in str(listed)
