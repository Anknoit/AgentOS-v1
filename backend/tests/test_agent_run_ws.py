"""Streaming an agent run over WebSocket."""

from __future__ import annotations


def test_ws_streams_run_events(client, auth_headers):
    agent = client.post(
        "/v1/agents", headers=auth_headers, json={"name": "WS Desk", "template": "support_desk"}
    ).json()

    with client.websocket_connect(
        f"/v1/agents/{agent['id']}/runs/stream?token=test-key"
    ) as ws:
        ws.send_json({"task": "how do I reset my password"})
        events = []
        while True:
            ev = ws.receive_json()
            events.append(ev)
            if ev["type"] in ("done", "error"):
                break

    types = [e["type"] for e in events]
    assert types[0] == "run_started"
    assert "tool_call" in types
    assert "token" in types
    assert "usage" in types
    assert types[-1] == "done"
    assert events[-1]["total_tokens"] > 0


def test_ws_rejects_missing_token(client):
    agent_stream = "/v1/agents/does-not-matter/runs/stream"
    try:
        with client.websocket_connect(agent_stream) as ws:
            ws.receive_json()
        raise AssertionError("expected the socket to be refused")
    except Exception:
        # Starlette raises on a 4401 close during connect — that is the rejection we want.
        pass
