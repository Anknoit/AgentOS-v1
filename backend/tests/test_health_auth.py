from __future__ import annotations


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"] == "sqlite"
    assert body["runtime"] == "inprocess"


def test_health_echoes_trace_id(client):
    r = client.get("/health", headers={"X-Trace-Id": "abc123"})
    assert r.headers["x-trace-id"] == "abc123"


def test_whoami_requires_auth(client):
    r = client.get("/v1/whoami")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


def test_whoami_with_key(client, auth_headers):
    r = client.get("/v1/whoami", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["tenant_id"]


def test_whoami_rejects_bad_key(client):
    r = client.get("/v1/whoami", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_metrics_exposed(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "agentos_http_requests_total" in r.text
