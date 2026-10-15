"""Stream tokens to the client over WebSocket (Phase 0 spike)."""

from __future__ import annotations

from tests.conftest import API_KEY


def test_ws_streams_tokens_and_usage(client, auth_headers):
    with client.websocket_connect(f"/v1/runs/stream?token={API_KEY}") as ws:
        ws.send_json({"task": "stream please"})
        events = []
        while True:
            ev = ws.receive_json()
            events.append(ev)
            if ev["type"] in ("done", "error"):
                break

    types = [e["type"] for e in events]
    assert types[0] == "run_started"
    assert "token" in types
    assert "usage" in types
    assert types[-1] == "done"

    usage = next(e for e in events if e["type"] == "usage")
    assert usage["total_tokens"] > 0

    # the streamed run's usage_event is persisted and queryable
    run_id = events[0]["run_id"]
    listed = client.get(f"/v1/usage?run_id={run_id}", headers=auth_headers).json()
    assert len(listed) == 1
    assert listed[0]["id"] == usage["usage_event_id"]


def test_ws_rejects_without_token(client):
    import pytest
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/v1/runs/stream") as ws:
            ws.receive_json()
