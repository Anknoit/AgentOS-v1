"""Payment gateway abstraction — Razorpay, plus a hermetic in-process mock (Phase 4).

Settlement is the riskiest part of the system (money movement), so the gateway is a thin,
swappable seam with one security-critical primitive: **HMAC-SHA256 signature verification**, used
to authenticate both the checkout callback and the webhook. Both the live ``RazorpayGateway`` and
the ``MockGateway`` run the *same* verification code — the mock only differs in that it also *signs*
(with the configured test secret) so the whole order → verify → webhook path is exercised with no
network, exactly like the mock LLM provider. A forged or tampered signature is rejected the same
way in both.

Razorpay charges in a currency's minor unit (paise for INR, cents for USD); the ledger stays in
USD nanodollars, so :mod:`app.billing.payments` records both what the wallet was credited and what
the gateway charged. Secrets come from settings (env only) and are never logged or returned.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Any

import httpx

from app.config.settings import Settings
from app.core.logging import get_logger

log = get_logger(__name__)

RAZORPAY_API = "https://api.razorpay.com/v1"


class GatewayError(Exception):
    """A gateway call failed (network, auth, or an unexpected response)."""


@dataclass(frozen=True)
class GatewayOrder:
    id: str
    amount_minor: int
    currency: str
    status: str
    receipt: str | None = None


def _sign(secret: str, message: str) -> str:
    """HMAC-SHA256 hex digest — Razorpay's signature scheme for callbacks and webhooks."""
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_payment_signature(
    secret: str, *, order_id: str, payment_id: str, signature: str
) -> bool:
    """Checkout callback: expected = HMAC(order_id|payment_id). Constant-time compare."""
    expected = _sign(secret, f"{order_id}|{payment_id}")
    return hmac.compare_digest(expected, signature or "")


def verify_webhook_signature(secret: str, *, raw_body: bytes, signature: str) -> bool:
    """Webhook: expected = HMAC(raw_request_body). Constant-time compare."""
    expected = _sign(secret, raw_body.decode("utf-8"))
    return hmac.compare_digest(expected, signature or "")


class RazorpayGateway:
    """Live Razorpay Orders API. ``client`` is injectable so tests never hit the network."""

    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        self._s = settings
        self._client = client

    @property
    def key_id(self) -> str:
        return self._s.razorpay_key_id

    async def create_order(
        self, *, amount_minor: int, currency: str, receipt: str, notes: dict[str, Any]
    ) -> GatewayOrder:
        client = self._client or httpx.AsyncClient(timeout=15.0)
        try:
            resp = await client.post(
                f"{RAZORPAY_API}/orders",
                auth=(self._s.razorpay_key_id, self._s.razorpay_key_secret),
                json={
                    "amount": amount_minor,
                    "currency": currency,
                    "receipt": receipt,
                    "notes": notes,
                },
            )
            if resp.status_code >= 400:
                raise GatewayError(f"razorpay order failed: {resp.status_code}")
            data = resp.json()
        except httpx.HTTPError as exc:  # pragma: no cover - network path
            raise GatewayError(str(exc)) from exc
        finally:
            if self._client is None:
                await client.aclose()
        return GatewayOrder(
            id=data["id"],
            amount_minor=int(data["amount"]),
            currency=data["currency"],
            status=data.get("status", "created"),
            receipt=data.get("receipt"),
        )

    def verify_payment(self, *, order_id: str, payment_id: str, signature: str) -> bool:
        return verify_payment_signature(
            self._s.razorpay_key_secret,
            order_id=order_id,
            payment_id=payment_id,
            signature=signature,
        )

    def verify_webhook(self, *, raw_body: bytes, signature: str) -> bool:
        return verify_webhook_signature(
            self._s.razorpay_webhook_secret, raw_body=raw_body, signature=signature
        )


class MockGateway:
    """In-process gateway for the dev/test profile — no network, deterministic, fully signed.

    Mirrors Razorpay's contract so the real verification code runs unchanged. The test/dev helpers
    :meth:`sign_payment` and :meth:`sign_webhook` produce the signatures a real client would return,
    so a caller can drive the complete order → verify → webhook flow offline.
    """

    def __init__(self, settings: Settings) -> None:
        self._s = settings

    @property
    def key_id(self) -> str:
        return self._s.razorpay_key_id

    async def create_order(
        self, *, amount_minor: int, currency: str, receipt: str, notes: dict[str, Any]
    ) -> GatewayOrder:
        return GatewayOrder(
            id=f"order_{secrets.token_hex(10)}",
            amount_minor=amount_minor,
            currency=currency,
            status="created",
            receipt=receipt,
        )

    def verify_payment(self, *, order_id: str, payment_id: str, signature: str) -> bool:
        return verify_payment_signature(
            self._s.razorpay_key_secret,
            order_id=order_id,
            payment_id=payment_id,
            signature=signature,
        )

    def verify_webhook(self, *, raw_body: bytes, signature: str) -> bool:
        return verify_webhook_signature(
            self._s.razorpay_webhook_secret, raw_body=raw_body, signature=signature
        )

    # --- test/dev helpers: produce what a real Razorpay client would send back ---
    def sign_payment(self, *, order_id: str, payment_id: str) -> str:
        return _sign(self._s.razorpay_key_secret, f"{order_id}|{payment_id}")

    def sign_webhook(self, payload: dict[str, Any]) -> tuple[bytes, str]:
        raw = json.dumps(payload).encode("utf-8")
        return raw, _sign(self._s.razorpay_webhook_secret, raw.decode("utf-8"))


def get_gateway(settings: Settings) -> RazorpayGateway | MockGateway:
    if settings.payment_provider == "razorpay":
        return RazorpayGateway(settings)
    return MockGateway(settings)
