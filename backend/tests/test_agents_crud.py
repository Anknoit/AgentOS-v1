"""Agent CRUD + immutable versioning."""

from __future__ import annotations


def test_create_agent_from_template(client, auth_headers):
    r = client.post(
        "/v1/agents",
        headers=auth_headers,
        json={"name": "Help Bot", "template": "support_desk"},
    )
    assert r.status_code == 201, r.text
    agent = r.json()
    assert agent["slug"] == "help-bot"
    assert agent["template"] == "support_desk"
    assert agent["status"] == "active"
    assert agent["current_version_id"]

    versions = client.get(f"/v1/agents/{agent['id']}/versions", headers=auth_headers).json()
    assert len(versions) == 1
    assert versions[0]["version"] == 1
    assert "kb_search" in versions[0]["tools"]
    assert versions[0]["system_prompt"]


def test_patch_config_mints_new_version(client, auth_headers):
    agent = client.post(
        "/v1/agents", headers=auth_headers, json={"name": "Desk", "template": "support_desk"}
    ).json()
    aid = agent["id"]
    first_version_id = agent["current_version_id"]

    r = client.patch(
        f"/v1/agents/{aid}",
        headers=auth_headers,
        json={"config": {"model": "gpt-4o", "system_prompt": "Be terse.", "tools": ["kb_search"]}},
    )
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["current_version_id"] != first_version_id

    versions = client.get(f"/v1/agents/{aid}/versions", headers=auth_headers).json()
    assert len(versions) == 2
    assert versions[0]["version"] == 2
    assert versions[0]["model"] == "gpt-4o"
    # The first version is immutable — still present and unchanged.
    assert versions[1]["version"] == 1


def test_list_and_get_agent(client, auth_headers):
    agent = client.post(
        "/v1/agents", headers=auth_headers, json={"name": "Listed", "template": "support_desk"}
    ).json()
    listing = client.get("/v1/agents", headers=auth_headers).json()
    assert any(a["id"] == agent["id"] for a in listing)
    got = client.get(f"/v1/agents/{agent['id']}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["id"] == agent["id"]


def test_agents_require_auth(client):
    assert client.get("/v1/agents").status_code == 401
    assert client.post("/v1/agents", json={"name": "x"}).status_code == 401


def test_unknown_template_rejected(client, auth_headers):
    r = client.post(
        "/v1/agents", headers=auth_headers, json={"name": "Bad", "template": "does_not_exist"}
    )
    assert r.status_code == 404
