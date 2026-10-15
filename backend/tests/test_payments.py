"""Razorpay top-up lifecycle — order → signed callback → wallet credit, and the money edge cases.

Everything runs against the in-process ``MockGateway``, which signs with the configured test
secret so the *real* HMAC verification path is exercised with no network.
"""

from __future__ import annotations

import pytest

from app.billing.gateway import MockGateway
from app.config import get_settings


def _topup_and_confirm(client, auth_headers, amount_usd="10"):
    created = client.post(
        "/v1/billing/topups", headers=auth_headers, json={"amount_usd": amount_usd}
    )
    assert created.status_code == 201, created.text
    order = created.json()
    gw = MockGateway(get_settings())
    payment_id = f"pay_{order['order_id'][6:]}"
    sig = gw.sign_payment(order_id=order["order_id"], payment_id=payment_id)
    confirmed = client.post(
        f"/v1/billing/topups/{order['order_id']}/confirm",
        headers=auth_headers,
        json={"razorpay_payment_id": payment_id, "razorpay_signature": sig},
    )
    return order, payment_id, confirmed


def test_topup_credits_wallet(client, auth_headers):
    before = client.get("/v1/wallet", headers=auth_headers).json()["balance_nanos"]
    order, _, confirmed = _topup_and_confirm(client, auth_headers, "10")
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["status"] == "paid"
    assert body["signature_verified"] is True
    assert order["amount_nanos"] == 10_000_000_000  # $10
    # Gateway charged in minor units (USD cents at fx 1): $10 -> 1000 cents.
    assert order["amount_minor"] == 1000

    after = client.get("/v1/wallet", headers=auth_headers).json()
    assert after["balance_nanos"] == before + 10_000_000_000


def test_topup_confirm_is_idempotent(client, auth_headers):
    """The checkout callback replayed (or racing the webhook) credits the wallet only once."""
    order, payment_id, first = _topup_and_confirm(client, auth_headers, "5")
    assert first.status_code == 200
    after_first = client.get("/v1/wallet", headers=auth_headers).json()["balance_nanos"]

    gw = MockGateway(get_settings())
    sig = gw.sign_payment(order_id=order["order_id"], payment_id=payment_id)
    second = client.post(
        f"/v1/billing/topups/{order['order_id']}/confirm",
        headers=auth_headers,
        json={"razorpay_payment_id": payment_id, "razorpay_signature": sig},
    )
    assert second.status_code == 200
    after_second = client.get("/v1/wallet", headers=auth_headers).json()["balance_nanos"]
    assert after_first == after_second  # no double credit


def test_forged_signature_credits_nothing(client, auth_headers):
    """A bad checkout signature is rejected and the wallet is untouched (double-spend guard)."""
    created = client.post(
        "/v1/billing/topups", headers=auth_headers, json={"amount_usd": "7"}
    ).json()
    before = client.get("/v1/wallet", headers=auth_headers).json()["balance_nanos"]
    resp = client.post(
        f"/v1/billing/topups/{created['order_id']}/confirm",
        headers=auth_headers,
        json={"razorpay_payment_id": "pay_forged", "razorpay_signature": "deadbeef"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "payment_error"
    after = client.get("/v1/wallet", headers=auth_headers).json()["balance_nanos"]
    assert after == before


def test_webhook_captures_payment(client, auth_headers):
    """A signed ``payment.captured`` webhook credits the wallet, idempotent with the callback."""
    created = client.post(
        "/v1/billing/topups", headers=auth_headers, json={"amount_usd": "3"}
    ).json()
    before = client.get("/v1/wallet", headers=auth_headers).json()["balance_nanos"]

    # The webhook carries the tenant in the order notes Razorpay signs back to us.
    tenant_id = client.get("/v1/whoami", headers=auth_headers).json()["tenant_id"]

    gw = MockGateway(get_settings())
    payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": f"pay_wh_{created['order_id'][6:]}",
                    "order_id": created["order_id"],
                    "method": "upi",
                    "notes": {"tenant_id": tenant_id},
                }
            }
        },
    }
    raw, sig = gw.sign_webhook(payload)
    resp = client.post(
        "/v1/webhooks/razorpay",
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
        content=raw,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["handled"] is True
    after = client.get("/v1/wallet", headers=auth_headers).json()["balance_nanos"]
    assert after == before + 3_000_000_000


def test_forged_webhook_rejected(client):
    resp = client.post(
        "/v1/webhooks/razorpay",
        headers={"X-Razorpay-Signature": "nope", "Content-Type": "application/json"},
        content=b'{"event":"payment.captured"}',
    )
    assert resp.status_code == 400


def test_refund_debits_wallet(client, auth_headers):
    _, _, confirmed = _topup_and_confirm(client, auth_headers, "8")
    payment_db_id = confirmed.json()["id"]
    before = client.get("/v1/wallet", headers=auth_headers).json()["balance_nanos"]

    refund = client.post(
        f"/v1/billing/payments/{payment_db_id}/refund",
        headers=auth_headers,
        json={"amount_usd": "3"},
    )
    assert refund.status_code == 200, refund.text
    assert refund.json()["refunded_nanos"] == 3_000_000_000
    after = client.get("/v1/wallet", headers=auth_headers).json()["balance_nanos"]
    assert after == before - 3_000_000_000

    # Can't refund more than remains.
    over = client.post(
        f"/v1/billing/payments/{payment_db_id}/refund",
        headers=auth_headers,
        json={"amount_usd": "100"},
    )
    assert over.status_code == 200
    assert over.json()["status"] == "refunded"  # the rest (5) refunded, capped at net


@pytest.mark.asyncio
async def test_mock_gateway_verifies_its_own_signatures():
    gw = MockGateway(get_settings())
    sig = gw.sign_payment(order_id="order_abc", payment_id="pay_xyz")
    assert gw.verify_payment(order_id="order_abc", payment_id="pay_xyz", signature=sig)
    assert not gw.verify_payment(order_id="order_abc", payment_id="pay_xyz", signature="bad")
