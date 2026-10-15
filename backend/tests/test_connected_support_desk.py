"""Phase 2 exit criterion, end to end.

A Support Desk agent reads from and posts to Slack and a CRM using scoped, tenant-isolated
credentials; an attempt to use an ungranted scope is denied and logged.
"""

from __future__ import annotations


def _store_credentials(client, auth_headers):
    client.post(
        "/v1/credentials",
        headers=auth_headers,
        json={"connector_key": "crm", "secret": "crm-key", "provider_meta": {"instance": "acme"}},
    )
    client.post(
        "/v1/credentials",
        headers=auth_headers,
        json={
            "connector_key": "slack",
            "secret": "xoxb-token",
            "provider_meta": {"workspace": "acme"},
        },
    )


def test_connected_support_desk_touches_slack_and_crm(client, auth_headers):
    _store_credentials(client, auth_headers)
    agent = client.post(
        "/v1/agents",
        headers=auth_headers,
        json={"name": "Connected Desk", "template": "support_desk_connected"},
    ).json()

    run = client.post(
        f"/v1/agents/{agent['id']}/runs",
        headers=auth_headers,
        json={"task": "I need a refund on my order"},
    ).json()
    assert run["status"] == "completed", run
    assert "refund" in run["output"].lower()

    actions = client.get(f"/v1/runs/{run['id']}/actions", headers=auth_headers).json()
    connector_actions = [a for a in actions if a["type"] == "connector_call"]
    tools_called = {a["name"] for a in connector_actions}
    assert "crm.search_contacts" in tools_called  # reads the CRM
    assert "crm.create_ticket" in tools_called     # writes the CRM
    assert "slack.post_message" in tools_called     # posts to Slack
    assert all(a["content"]["outcome"] == "ok" for a in connector_actions)
    # the credential was actually used (non-secret workspace surfaced from the vault)
    slack_action = next(a for a in connector_actions if a["name"] == "slack.post_message")
    assert slack_action["content"]["result"]["workspace"] == "acme"

    # each granted connector call is metered
    usage = client.get(f"/v1/usage?run_id={run['id']}", headers=auth_headers).json()
    connector_usage = [u for u in usage if u["event_type"] == "connector_call"]
    assert len(connector_usage) == 3
    assert all(u["run_id"] == run["id"] for u in connector_usage)


def test_ungranted_scope_denied_and_logged_in_run(client, auth_headers):
    # Only a CRM credential, and the agent is granted crm:read but NOT crm:write.
    client.post(
        "/v1/credentials",
        headers=auth_headers,
        json={"connector_key": "crm", "secret": "crm-key", "provider_meta": {"instance": "acme"}},
    )
    agent = client.post(
        "/v1/agents",
        headers=auth_headers,
        json={
            "name": "Read-only Desk",
            "config": {
                "system_prompt": "You are a read-only support agent.",
                "tools": ["kb_search"],
                "connector_bindings": {"crm": {"scopes": ["crm:read"]}},
            },
        },
    ).json()

    run = client.post(
        f"/v1/agents/{agent['id']}/runs",
        headers=auth_headers,
        json={"task": "I need a refund"},
    ).json()
    # the run still completes — a denied call is handled, not fatal
    assert run["status"] == "completed", run

    actions = client.get(f"/v1/runs/{run['id']}/actions", headers=auth_headers).json()
    by_tool = {a["name"]: a for a in actions if a["type"] == "connector_call"}
    # the granted read happened...
    assert by_tool["crm.search_contacts"]["content"]["outcome"] == "ok"
    # ...and the ungranted write was denied and logged
    assert by_tool["crm.create_ticket"]["content"]["outcome"] == "denied"
    assert by_tool["crm.create_ticket"]["content"]["scope"] == "crm:write"

    # the denied write did no billable work
    usage = client.get(f"/v1/usage?run_id={run['id']}", headers=auth_headers).json()
    assert len([u for u in usage if u["event_type"] == "connector_call"]) == 1
