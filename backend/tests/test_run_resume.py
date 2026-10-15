"""Durability: a run resumes from its checkpoint after a crash, without double-counting usage.

This is the Phase 1 exit criterion's "resumable across a worker restart" claim, demonstrated on
the SQLite dev-fallback: the model node crashes on its first execution (simulating a worker dying
mid-run), the run is left resumable with its checkpoint intact, and resuming completes it — with
the tool step (which already ran and metered) *not* re-counted, because usage events dedupe on
their deterministic idempotency keys.
"""

from __future__ import annotations


def test_run_resumes_after_crash_without_double_counting(client, auth_headers, monkeypatch):
    from app.runtime import providers
    from app.runtime.providers import MockProvider

    real = MockProvider()
    calls = {"n": 0}

    class FlakyProvider:
        name = "mock"

        async def stream(self, prompt, *, model):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated worker crash mid-run")
            async for chunk in real.stream(prompt, model=model):
                yield chunk

    # The kernel routes the model node through build_router, which (failover off) wraps the single
    # provider from get_provider — patch that seam so the first model call crashes mid-run.
    monkeypatch.setattr(providers, "get_provider", lambda _settings: FlakyProvider())

    agent = client.post(
        "/v1/agents",
        headers=auth_headers,
        json={"name": "Resumable", "template": "support_desk"},
    ).json()

    # First attempt crashes inside the model node (after the tool node has run + metered).
    run = client.post(
        f"/v1/agents/{agent['id']}/runs",
        headers=auth_headers,
        json={"task": "I need a refund"},
    ).json()
    assert run["status"] == "failed"

    # The tool step already captured its usage event before the crash.
    usage_after_crash = client.get(
        f"/v1/usage?run_id={run['id']}", headers=auth_headers
    ).json()
    assert [u["event_type"] for u in usage_after_crash] == ["tool_call"]

    # Resume from the checkpoint — the kernel re-enters at the model node and finishes.
    resumed = client.post(f"/v1/runs/{run['id']}/resume", headers=auth_headers)
    assert resumed.status_code == 202, resumed.text
    run2 = resumed.json()
    assert run2["status"] == "completed"
    assert "refund" in run2["output"].lower()
    assert run2["tool_calls"] == 1  # the tool node was not re-run

    # Exactly one of each usage event despite the crash + resume (exactly-once accounting).
    usage = client.get(f"/v1/usage?run_id={run['id']}", headers=auth_headers).json()
    assert sorted(u["event_type"] for u in usage) == ["model_call", "tool_call"]
