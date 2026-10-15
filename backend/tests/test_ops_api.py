"""The scale & reliability ops surface (Phase 5).

Smoke-level coverage that the tenant-scoped /v1/ops endpoints are wired and shaped correctly; the
behaviour they expose is proven in test_stream_replay, test_fair_scheduler, and
test_provider_router.
"""

from __future__ import annotations


def test_ops_endpoints_require_auth(client):
    for path in ("/v1/ops/stream", "/v1/ops/scheduler", "/v1/ops/providers"):
        assert client.get(path).status_code == 401, path


def test_scheduler_stats_shape(client, auth_headers):
    stats = client.get("/v1/ops/scheduler", headers=auth_headers).json()
    assert stats["max_concurrency"] >= 1
    assert stats["per_tenant_concurrency"] >= 1
    assert stats["tenant_running"] >= 0
    assert stats["tenant_waiting"] >= 0


def test_provider_health_shape(client, auth_headers):
    health = client.get("/v1/ops/providers", headers=auth_headers).json()
    assert isinstance(health["failover_enabled"], bool)
    assert isinstance(health["candidates"], list)
    assert isinstance(health["providers"], dict)


def test_stream_health_shape(client, auth_headers):
    health = client.get("/v1/ops/stream", headers=auth_headers).json()
    for key in ("head_offset", "event_count", "committed_offset", "lag"):
        assert key in health
        assert health[key] >= 0
