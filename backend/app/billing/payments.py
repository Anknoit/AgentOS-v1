"""Top-up lifecycle — create a gateway order, confirm it, reconcile the webhook, refund (Phase 4).

This is the money-in path. It is written so the two ways a payment is confirmed — the synchronous
checkout callback (:func:`confirm_topup`) and the asynchronous webhook (:func:`handle_webhook`) —
converge on the same ``payment`` row and credit the wallet **exactly once**, because the credit is
posted under the ledger's ``(tenant_id, ref)`` uniqueness and guarded by the row's
``ledger_entry_id``. A forged signature never credits anything.

The webhook authenticates with the deployment webhook secret (HMAC over the raw body); the tenant
is taken from the order ``notes`` we set at creation — which Razorpay signs back to us — so no
privileged cross-tenant read is needed to route it.
"""

from __future__ import annotations

import json
import secrets
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select

from app.billing import wallet_ops
from app.billing.gateway import get_gateway
from app.config.settings import get_settings
from app.core.context import get_trace_id
from app.core.errors import NotFoundError, PaymentError
from app.core.logging import get_logger
from app.db.session import tenant_session
from app.metering.money import NANOS_PER_USD, format_usd, usd_to_nanos
from app.models.payment import Payment
from app.schemas.billing import PaymentOut, TopupOut

log = get_logger(__name__)


def _to_gateway_minor(amount_nanos: int) -> tuple[int, str]:
    """Convert a USD nanodollar amount to the gateway's minor unit and currency."""
    s = get_settings()
    usd = Decimal(amount_nanos) / Decimal(NANOS_PER_USD)
    minor = usd * Decimal(s.razorpay_minor_per_unit) * Decimal(s.razorpay_fx_usd_to_gateway)
    return int(minor.quantize(Decimal(1), rounding=ROUND_HALF_UP)), s.razorpay_currency


def _gateway_minor_to_nanos(minor: int) -> int:
    """Invert :func:`_to_gateway_minor` — what the gateway charged, back in USD nanodollars."""
    s = get_settings()
    scale = Decimal(s.razorpay_minor_per_unit) * Decimal(s.razorpay_fx_usd_to_gateway)
    return usd_to_nanos(Decimal(minor) / scale)


async def create_topup(tenant_id: str, amount_usd: Decimal) -> TopupOut:
    """Create a gateway order for a top-up and persist a ``created`` payment to confirm later."""
    settings = get_settings()
    gateway = get_gateway(settings)
    amount_nanos = usd_to_nanos(amount_usd)
    if amount_nanos <= 0:
        raise PaymentError("top-up amount must be positive")
    minor, gw_currency = _to_gateway_minor(amount_nanos)
    receipt = f"topup_{secrets.token_hex(8)}"
    trace_id = get_trace_id()

    order = await gateway.create_order(
        amount_minor=minor,
        currency=gw_currency,
        receipt=receipt,
        # Razorpay signs these back to us in the webhook, so the tenant routes without a lookup.
        notes={"tenant_id": tenant_id, "receipt": receipt},
    )

    payment = Payment(
        tenant_id=tenant_id,
        provider=settings.payment_provider if settings.payment_provider != "mock" else "razorpay",
        order_id=order.id,
        status="created",
        amount_nanos=amount_nanos,
        currency="USD",
        gateway_amount_minor=order.amount_minor,
        gateway_currency=order.currency,
        receipt=receipt,
        trace_id=trace_id,
        detail={"notes": {"tenant_id": tenant_id}},
    )
    async with tenant_session(tenant_id) as session:
        session.add(payment)
        await session.flush()
        payment_db_id = payment.id
    log.info("topup.created", tenant_id=tenant_id, order_id=order.id, amount_nanos=amount_nanos)
    return TopupOut(
        payment_id=payment_db_id,
        order_id=order.id,
        key_id=gateway.key_id,
        amount_minor=order.amount_minor,
        gateway_currency=order.currency,
        amount_nanos=amount_nanos,
        amount_usd=format_usd(amount_nanos),
        receipt=receipt,
    )


async def _settle_paid(
    tenant_id: str, order_id: str, *, payment_id: str, method: str | None, signature_verified: bool
) -> Payment:
    """Mark an order paid and credit the wallet once (idempotent on the payment row + ledger ref).

    Shared by the checkout callback and the webhook. Both run under the wallet row's lock, so the
    second to arrive sees ``ledger_entry_id`` already set (or the ledger ``ref`` already taken) and
    credits nothing further.
    """
    settings = get_settings()
    async with tenant_session(tenant_id) as session:
        payment = (
            await session.execute(
                select(Payment).where(
                    Payment.tenant_id == tenant_id, Payment.order_id == order_id
                )
            )
        ).scalar_one_or_none()
        if payment is None:
            raise NotFoundError(f"payment for order '{order_id}' not found")

        payment.payment_id = payment_id
        payment.signature_verified = signature_verified or payment.signature_verified
        if method:
            payment.method = method
        if payment.ledger_entry_id is not None:  # already credited
            return payment

        entry = await wallet_ops.post_movement(
            session,
            tenant_id=tenant_id,
            amount_nanos=payment.amount_nanos,
            entry_type="topup",
            ref=f"topup:{payment_id}",
            provider=payment.provider,
            sign=1,
            detail={"order_id": order_id, "payment_id": payment_id, "method": method},
            enable_enforce=settings.enforce_balance_on_topup,
        )
        payment.status = "paid"
        if entry is not None:
            payment.ledger_entry_id = entry.id
    log.info("topup.paid", tenant_id=tenant_id, order_id=order_id, payment_id=payment_id)
    return payment


async def confirm_topup(
    tenant_id: str, order_id: str, *, razorpay_payment_id: str, razorpay_signature: str
) -> PaymentOut:
    """Verify the checkout callback signature and credit the wallet."""
    gateway = get_gateway(get_settings())
    if not gateway.verify_payment(
        order_id=order_id, payment_id=razorpay_payment_id, signature=razorpay_signature
    ):
        # Record the failed attempt for audit, but credit nothing.
        async with tenant_session(tenant_id) as session:
            payment = (
                await session.execute(
                    select(Payment).where(
                        Payment.tenant_id == tenant_id, Payment.order_id == order_id
                    )
                )
            ).scalar_one_or_none()
            if payment is not None and payment.ledger_entry_id is None:
                payment.detail = {**payment.detail, "signature_failed": True}
        log.warning("topup.bad_signature", tenant_id=tenant_id, order_id=order_id)
        raise PaymentError("payment signature verification failed")

    payment = await _settle_paid(
        tenant_id, order_id, payment_id=razorpay_payment_id, method=None, signature_verified=True
    )
    return PaymentOut.model_validate(payment)


async def handle_webhook(raw_body: bytes, signature: str) -> dict[str, Any]:
    """Authenticate and apply a Razorpay webhook, reconciling it into the ledger.

    Handles ``payment.captured`` (credit), ``payment.failed`` (mark failed), and
    ``refund.processed`` (debit). Idempotent against the checkout callback having already settled.
    """
    gateway = get_gateway(get_settings())
    if not gateway.verify_webhook(raw_body=raw_body, signature=signature):
        log.warning("webhook.bad_signature")
        raise PaymentError("webhook signature verification failed")

    try:
        event = json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise PaymentError("webhook body is not valid JSON") from exc

    kind = event.get("event", "")
    entity = (
        event.get("payload", {}).get("payment", {}).get("entity", {})
        or event.get("payload", {}).get("refund", {}).get("entity", {})
    )
    order_id = entity.get("order_id")
    tenant_id = (entity.get("notes") or {}).get("tenant_id")
    if not order_id or not tenant_id:
        log.info("webhook.ignored", event=kind)
        return {"handled": False, "event": kind}

    if kind == "payment.captured":
        await _settle_paid(
            tenant_id,
            order_id,
            payment_id=entity.get("id", order_id),
            method=entity.get("method"),
            signature_verified=True,
        )
        return {"handled": True, "event": kind, "order_id": order_id}

    if kind == "payment.failed":
        async with tenant_session(tenant_id) as session:
            payment = (
                await session.execute(
                    select(Payment).where(
                        Payment.tenant_id == tenant_id, Payment.order_id == order_id
                    )
                )
            ).scalar_one_or_none()
            if payment is not None and payment.ledger_entry_id is None:
                payment.status = "failed"
                payment.payment_id = entity.get("id")
        log.info("webhook.payment_failed", tenant_id=tenant_id, order_id=order_id)
        return {"handled": True, "event": kind, "order_id": order_id}

    if kind == "refund.processed":
        refund_id = entity.get("id", f"rfnd_{order_id}")
        amount_minor = int(entity.get("amount", 0))
        await _apply_refund(
            tenant_id,
            order_id,
            refund_id=refund_id,
            amount_nanos=_gateway_minor_to_nanos(amount_minor),
        )
        return {"handled": True, "event": kind, "order_id": order_id}

    log.info("webhook.ignored", event=kind)
    return {"handled": False, "event": kind}


async def _apply_refund(
    tenant_id: str, order_id: str, *, refund_id: str, amount_nanos: int | None
) -> Payment:
    """Debit the wallet for a refund against a settled payment (idempotent on the refund id)."""
    async with tenant_session(tenant_id) as session:
        payment = (
            await session.execute(
                select(Payment).where(
                    Payment.tenant_id == tenant_id, Payment.order_id == order_id
                )
            )
        ).scalar_one_or_none()
        if payment is None:
            raise NotFoundError(f"payment for order '{order_id}' not found")
        if payment.ledger_entry_id is None:
            raise PaymentError("cannot refund a payment that was never settled")

        net = payment.amount_nanos - payment.refunded_nanos
        amount = net if amount_nanos is None else min(amount_nanos, net)
        if amount <= 0:
            raise PaymentError("nothing left to refund")

        entry = await wallet_ops.post_movement(
            session,
            tenant_id=tenant_id,
            amount_nanos=amount,
            entry_type="refund",
            ref=f"refund:{refund_id}",
            provider=payment.provider,
            sign=-1,
            detail={"order_id": order_id, "payment_id": payment.payment_id, "refund_id": refund_id},
        )
        if entry is not None:  # not a replay
            payment.refunded_nanos += amount
            if payment.refunded_nanos >= payment.amount_nanos:
                payment.status = "refunded"
    log.info("refund.applied", tenant_id=tenant_id, order_id=order_id, amount_nanos=amount)
    return payment


async def refund_payment(
    tenant_id: str, payment_db_id: str, amount_nanos: int | None
) -> PaymentOut:
    """Operator-initiated refund by our payment row id."""
    async with tenant_session(tenant_id) as session:
        payment = (
            await session.execute(
                select(Payment).where(Payment.tenant_id == tenant_id, Payment.id == payment_db_id)
            )
        ).scalar_one_or_none()
        if payment is None:
            raise NotFoundError(f"payment '{payment_db_id}' not found")
        order_id = payment.order_id
    refund_id = f"manual_{secrets.token_hex(6)}"
    payment = await _apply_refund(
        tenant_id, order_id, refund_id=refund_id, amount_nanos=amount_nanos
    )
    return PaymentOut.model_validate(payment)


async def list_payments(tenant_id: str) -> list[PaymentOut]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                select(Payment)
                .where(Payment.tenant_id == tenant_id)
                .order_by(Payment.created_at.desc())
            )
        ).scalars().all()
        return [PaymentOut.model_validate(r) for r in rows]
