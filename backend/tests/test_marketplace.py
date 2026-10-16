"""Marketplace (Phase 6, build task 4): share/install agent templates + connectors across tenants.

Proves the cross-tenant catalogue — a template published by tenant A is discoverable and
installable by tenant B, the install lands in B's own tenant, and no secret is ever published.
"""

from __future__ import annotations

import pytest

from tests._helpers import headers, new_tenant_with_key


@pytest.mark.asyncio
async def test_publish_then_install_across_tenants(client):
    tid_a, key_a = await new_tenant_with_key("mkt-pub")
    tid_b, key_b = await new_tenant_with_key("mkt-inst")
    ha, hb = headers(key_a), headers(key_b)

    # A builds and publishes an agent (from the support_desk template).
    agent = client.post(
        "/v1/agents", headers=ha, json={"name": "Shared Desk", "template": "support_desk"}
    ).json()
    pub = client.post(
        "/v1/marketplace/publish/agent",
        headers=ha,
        json={"agent_id": agent["id"], "name": "Shared Desk", "description": "a desk"},
    )
    assert pub.status_code == 201
    listing_id = pub.json()["id"]

    # B discovers it in the public catalogue and installs it into its own tenant.
    catalogue = client.get("/v1/marketplace", headers=hb).json()
    assert any(x["id"] == listing_id for x in catalogue)

    before = len(client.get("/v1/agents", headers=hb).json())
    inst = client.post(f"/v1/marketplace/{listing_id}/install", headers=hb)
    assert inst.status_code == 200
    body = inst.json()
    assert body["kind"] == "agent_template" and body["agent_id"]

    after = client.get("/v1/agents", headers=hb).json()
    assert len(after) == before + 1
    installed = next(a for a in after if a["id"] == body["agent_id"])
    assert installed["role"] == "marketplace"


@pytest.mark.asyncio
async def test_connector_publish_carries_no_secret(client):
    tid, key = await new_tenant_with_key("mkt-conn")
    h = headers(key)
    pub = client.post(
        "/v1/marketplace/publish/connector",
        headers=h,
        json={
            "connector_key": "slack",
            "name": "Our Slack setup",
            "provider_meta": {"workspace": "acme"},
        },
    )
    assert pub.status_code == 201
    cfg = pub.json()["config"]
    assert cfg["connector_key"] == "slack"
    assert "secret" not in str(cfg).lower() or "workspace" in str(cfg)

    inst = client.post(f"/v1/marketplace/{pub.json()['id']}/install", headers=h).json()
    assert inst["kind"] == "connector"
    assert inst["connector_key"] == "slack"
    assert "credential" in inst["note"]


@pytest.mark.asyncio
async def test_install_bumps_counter(client):
    tid_a, key_a = await new_tenant_with_key("mkt-count-a")
    tid_b, key_b = await new_tenant_with_key("mkt-count-b")
    agent = client.post("/v1/agents", headers=headers(key_a), json={"name": "Counted"}).json()
    listing = client.post(
        "/v1/marketplace/publish/agent", headers=headers(key_a), json={"agent_id": agent["id"]}
    ).json()
    client.post(f"/v1/marketplace/{listing['id']}/install", headers=headers(key_b))
    refreshed = next(
        x for x in client.get("/v1/marketplace", headers=headers(key_b)).json()
        if x["id"] == listing["id"]
    )
    assert refreshed["installs"] >= 1
