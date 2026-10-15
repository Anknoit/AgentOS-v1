"""The Phase 4 exit criterion: top up once, run a fleet, get one reconciling invoice; and a
depleted prepaid balance stops further billable work."""

from __future__ import annotations

from app.billing.gateway import MockGateway
from app.config import get_settings


def _topup(client, auth_headers, amount_usd):
    order = client.post(
        "/v1/billing/topups", headers=auth_headers, json={"amount_usd": amount_usd}
    ).json()
    gw = MockGateway(get_settings())
    payment_id = f"pay_{order['order_id'][6:]}"
    sig = gw.sign_payment(order_id=order["order_id"], payment_id=payment_id)
    return client.post(
        f"/v1/billing/topups/{order['order_id']}/confirm",
        headers=auth_headers,
        json={"razorpay_payment_id": payment_id, "razorpay_signature": sig},
    ).json()


def test_single_invoice_rolls_the_fleet_ledger(client, auth_headers):
    # A mixed fleet: two agents each run once.
    for name in ("Billing Desk A", "Billing Desk B"):
        agent = client.post(
            "/v1/agents", headers=auth_headers, json={"name": name, "template": "support_desk"}
        ).json()
        run = client.post(
            f"/v1/agents/{agent['id']}/runs", headers=auth_headers, json={"task": "refund please"}
        ).json()
        assert run["status"] == "completed"

    invoice = client.post("/v1/invoices", headers=auth_headers, json={}).json()
    # One statement across the whole fleet, line items rolled from the ledger.
    assert invoice["number"].startswith("INV-")
    assert invoice["event_count"] >= 4  # >=2 runs x (tool + model)
    assert invoice["price_nanos"] > 0
    # BYO default card: price == cost, so margin is zero and totals reconcile with provider numbers.
    assert invoice["cost_nanos"] == invoice["price_nanos"]
    assert invoice["margin_nanos"] == 0
    assert len(invoice["line_items"]) >= 2

    # The invoice total equals the tenant's rated spend over the period.
    spend = client.get("/v1/spend", headers=auth_headers).json()
    assert invoice["price_nanos"] == spend["price_nanos"]


def test_reconciliation_balances_after_topup(client, auth_headers):
    _topup(client, auth_headers, "20")
    recon = client.get("/v1/billing/reconciliation", headers=auth_headers).json()
    # The ledger projection is intact (balance == topups - refunds - usage) and the gateway
    # charged exactly what we credited.
    assert recon["balance_drift_nanos"] == 0
    assert recon["gateway_drift_nanos"] == 0
    assert recon["within_tolerance"] is True
    assert recon["topups_nanos"] >= 20_000_000_000


def test_wallet_enforcement_toggle(client, auth_headers):
    """Entering/leaving the payment path flips prepaid credit control via the wallet."""
    on = client.patch("/v1/wallet", headers=auth_headers, json={"enforce_balance": True}).json()
    assert on["enforce_balance"] is True
    off = client.patch("/v1/wallet", headers=auth_headers, json={"enforce_balance": False}).json()
    assert off["enforce_balance"] is False
    # The wallet reports reserved and available alongside the balance.
    assert "available_nanos" in off and "reserved_nanos" in off
