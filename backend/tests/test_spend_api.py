"""The spend view — per-agent / per-run cost, wallet, and active pricing."""

from __future__ import annotations


def _run_agent(client, auth_headers, name):
    agent = client.post(
        "/v1/agents", headers=auth_headers, json={"name": name, "template": "support_desk"}
    ).json()
    run = client.post(
        f"/v1/agents/{agent['id']}/runs", headers=auth_headers, json={"task": "help me"}
    ).json()
    return agent, run


def test_spend_by_run_and_agent(client, auth_headers):
    agent, run = _run_agent(client, auth_headers, "Spendy Desk")

    # Per-run spend: exactly this run's two billable events.
    by_run = client.get(f"/v1/spend?run_id={run['id']}", headers=auth_headers).json()
    assert by_run["scope"] == "run"
    assert by_run["event_count"] == 2
    assert by_run["price_nanos"] > 0

    # Per-agent spend attributes cost to the agent that incurred it.
    by_agent = client.get("/v1/spend/agents", headers=auth_headers).json()
    mine = next(a for a in by_agent if a["agent_id"] == agent["id"])
    assert mine["agent_name"] == "Spendy Desk"
    assert mine["price_nanos"] == by_run["price_nanos"]
    assert mine["cost_usd"].startswith("$")


def test_tenant_spend_and_wallet_consistent(client, auth_headers):
    _run_agent(client, auth_headers, "Another Desk")
    total = client.get("/v1/spend", headers=auth_headers).json()
    wallet = client.get("/v1/wallet", headers=auth_headers).json()
    assert total["scope"] == "tenant"
    assert total["price_nanos"] > 0
    # wallet balance is the negative of accrued spend (BYO: no top-ups yet)
    assert wallet["balance_nanos"] == -total["price_nanos"]
    assert wallet["enforce_balance"] is False


def test_rate_cards_endpoint_exposes_default(client, auth_headers):
    cards = client.get("/v1/rate-cards", headers=auth_headers).json()
    assert len(cards) >= 1
    default = next(c for c in cards if c["name"] == "default")
    assert default["is_active"] is True
    assert default["model_prices"]["gpt-4o-mini"]["input"] == "0.15"
    assert default["markup_pct"] == "0"
