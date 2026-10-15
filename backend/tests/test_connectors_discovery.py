"""Connector discovery: the catalogue the UI renders and agents bind against."""

from __future__ import annotations


def test_list_connectors(client, auth_headers):
    r = client.get("/v1/connectors", headers=auth_headers)
    assert r.status_code == 200, r.text
    by_key = {c["key"]: c for c in r.json()}
    # the three real connectors + the generic MCP escape hatch
    assert {"slack", "crm", "http", "mcp"} <= set(by_key)

    slack = by_key["slack"]
    assert slack["auth_type"] == "oauth"
    assert "messaging" in slack["capabilities"]
    tool_names = {t["name"] for t in slack["tools"]}
    assert {"slack.post_message", "slack.list_messages"} <= tool_names
    # write and read are distinct scopes so they can be granted independently
    scopes = {t["scope"] for t in slack["tools"]}
    assert {"chat:write", "channels:read"} <= scopes


def test_get_connector_includes_tool_schemas(client, auth_headers):
    r = client.get("/v1/connectors/crm", headers=auth_headers)
    assert r.status_code == 200
    crm = r.json()
    ticket = next(t for t in crm["tools"] if t["name"] == "crm.create_ticket")
    assert ticket["scope"] == "crm:write"
    assert ticket["input_schema"]["type"] == "object"


def test_unknown_connector_404(client, auth_headers):
    assert client.get("/v1/connectors/nope", headers=auth_headers).status_code == 404


def test_discovery_requires_auth(client):
    assert client.get("/v1/connectors").status_code == 401
