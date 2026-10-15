"""Support Desk run end to end: config → run → audit log → usage (the Phase 1 exit criterion)."""

from __future__ import annotations


def _create_support_desk(client, auth_headers, name="Desk"):
    return client.post(
        "/v1/agents", headers=auth_headers, json={"name": name, "template": "support_desk"}
    ).json()


def test_support_desk_run_completes_with_grounding(client, auth_headers):
    agent = _create_support_desk(client, auth_headers)
    r = client.post(
        f"/v1/agents/{agent['id']}/runs",
        headers=auth_headers,
        json={"task": "I need a refund on my order"},
    )
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["status"] == "completed"
    assert run["total_tokens"] > 0
    assert run["tool_calls"] == 1
    # The tool's knowledge grounds the final answer.
    assert "refund" in run["output"].lower()


def test_run_has_complete_ordered_action_log(client, auth_headers):
    agent = _create_support_desk(client, auth_headers)
    run = client.post(
        f"/v1/agents/{agent['id']}/runs",
        headers=auth_headers,
        json={"task": "what are your support hours"},
    ).json()
    actions = client.get(f"/v1/runs/{run['id']}/actions", headers=auth_headers).json()

    types = [a["type"] for a in actions]
    names = [a["name"] for a in actions]
    seqs = [a["seq"] for a in actions]

    assert types[0] == "run_started"
    assert types[-1] == "run_completed"
    assert "triage" in names
    assert "tool_call" in types
    assert "model_call" in types
    assert seqs == sorted(seqs)
    # every row carries the run's trace id
    trace_ids = {a["trace_id"] for a in actions}
    assert len(trace_ids) == 1


def test_run_captures_one_model_and_one_tool_usage_event(client, auth_headers):
    agent = _create_support_desk(client, auth_headers)
    run = client.post(
        f"/v1/agents/{agent['id']}/runs",
        headers=auth_headers,
        json={"task": "how do I reset my password"},
    ).json()

    usage = client.get(f"/v1/usage?run_id={run['id']}", headers=auth_headers).json()
    kinds = sorted(u["event_type"] for u in usage)
    assert kinds == ["model_call", "tool_call"]
    # usage events are attributed to the agent and run
    assert all(u["run_id"] == run["id"] for u in usage)
    assert all(u["agent_id"] == agent["id"] for u in usage)
    # the model call links back to its action-log row via usage_event_id
    actions = client.get(f"/v1/runs/{run['id']}/actions", headers=auth_headers).json()
    model_action = next(a for a in actions if a["type"] == "model_call")
    assert model_action["usage_event_id"]


def test_run_listed_for_agent(client, auth_headers):
    agent = _create_support_desk(client, auth_headers)
    run = client.post(
        f"/v1/agents/{agent['id']}/runs", headers=auth_headers, json={"task": "hello"}
    ).json()
    runs = client.get(f"/v1/runs?agent_id={agent['id']}", headers=auth_headers).json()
    assert any(x["id"] == run["id"] for x in runs)
    detail = client.get(f"/v1/runs/{run['id']}", headers=auth_headers).json()
    assert detail["agent_version_id"] == agent["current_version_id"]
