"""Online credit control — the Phase 3 exit criterion: a hard cap stops an agent at the limit."""

from __future__ import annotations


def _make_agent(client, auth_headers, name):
    return client.post(
        "/v1/agents", headers=auth_headers, json={"name": name, "template": "support_desk"}
    ).json()


def test_hard_budget_stops_agent_at_limit(client, auth_headers):
    agent = _make_agent(client, auth_headers, "Capped Desk")
    # Agent-scoped so prior tests' spend can't pre-trip it; cap below one run's spend.
    budget = client.post(
        "/v1/budgets",
        headers=auth_headers,
        json={
            "name": "tiny",
            "scope": "agent",
            "scope_id": agent["id"],
            "period": "total",
            "limit_usd": "0.0005",
            "enforcement": "hard",
        },
    )
    assert budget.status_code == 201, budget.text

    run = client.post(
        f"/v1/agents/{agent['id']}/runs", headers=auth_headers, json={"task": "I need a refund"}
    ).json()

    # The agent ran up to the cap (the first billable step) and then stopped — not failed.
    assert run["status"] == "stopped", run

    # A hard-budget alert was logged, attributable to the run.
    alerts = client.get(f"/v1/alerts?run_id={run['id']}", headers=auth_headers).json()
    kinds = {a["kind"] for a in alerts}
    assert "budget_hard" in kinds
    hard = next(a for a in alerts if a["kind"] == "budget_hard")
    assert hard["severity"] == "critical"

    # The model call (the step the cap denied) never billed — the agent stopped at the limit.
    usage = client.get(f"/v1/usage?run_id={run['id']}", headers=auth_headers).json()
    kinds = {u["event_type"] for u in usage}
    assert "model_call" not in kinds

    # Spend stayed bounded (no runaway past the cap by more than the crossing step).
    spend = client.get(f"/v1/spend?run_id={run['id']}", headers=auth_headers).json()
    assert spend["price_nanos"] <= 2_000_000  # one tool call, nothing more


def test_soft_budget_alerts_but_completes(client, auth_headers):
    agent = _make_agent(client, auth_headers, "Soft Desk")
    client.post(
        "/v1/budgets",
        headers=auth_headers,
        json={
            "name": "soft",
            "scope": "agent",
            "scope_id": agent["id"],
            "period": "total",
            "limit_usd": "0.0005",
            "enforcement": "soft",
        },
    )
    run = client.post(
        f"/v1/agents/{agent['id']}/runs", headers=auth_headers, json={"task": "I need a refund"}
    ).json()
    # Soft cap only warns — the run completes.
    assert run["status"] == "completed", run
    alerts = client.get(f"/v1/alerts?run_id={run['id']}", headers=auth_headers).json()
    assert any(a["kind"] == "budget_soft" for a in alerts)


def test_budget_crud_api(client, auth_headers):
    created = client.post(
        "/v1/budgets",
        headers=auth_headers,
        json={"name": "monthly-cap", "period": "monthly", "limit_usd": "100"},
    ).json()
    assert created["limit_nanos"] == 100_000_000_000
    assert created["limit_usd"] == "$100"
    assert created["remaining_nanos"] <= created["limit_nanos"]

    listed = client.get("/v1/budgets", headers=auth_headers).json()
    assert any(b["id"] == created["id"] for b in listed)

    assert client.delete(f"/v1/budgets/{created['id']}", headers=auth_headers).status_code == 204
    listed = client.get("/v1/budgets", headers=auth_headers).json()
    assert not any(b["id"] == created["id"] for b in listed)
