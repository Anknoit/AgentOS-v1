"""The Phase 0 spike, end to end: run an agent loop and capture exactly one usage_event."""

from __future__ import annotations


def test_run_sync_captures_usage(client, auth_headers):
    r = client.post("/v1/runs/sync", json={"task": "ping"}, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["usage_event_id"]
    assert body["total_tokens"] > 0
    assert "ping" in body["output"]  # mock provider echoes the task


def test_usage_event_persisted_and_listed(client, auth_headers):
    run = client.post("/v1/runs/sync", json={"task": "hello world"}, headers=auth_headers).json()
    events = client.get(f"/v1/usage?run_id={run['run_id']}", headers=auth_headers).json()
    assert len(events) == 1
    ev = events[0]
    assert ev["id"] == run["usage_event_id"]
    assert ev["event_type"] == "model_call"
    assert ev["provider"] == "mock"
    assert ev["total_tokens"] == run["total_tokens"]
    assert ev["rated"] is False  # not rated until Phase 3


def test_trigger_run_inprocess(client, auth_headers):
    r = client.post("/v1/runs", json={"task": "do a thing"}, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["enqueued"] is False  # no Redis => in-process
    assert body["run_id"]
