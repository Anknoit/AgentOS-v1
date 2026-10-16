"""Settlement endpoints — top-ups, payments, invoices, reconciliation (Phase 4).

The payment path: a tenant tops up the wallet through Razorpay, the balance debits as agents run
(Phase 3 metering), and a single itemized invoice rolls the ledger. The **webhook** is the one
route here without tenant auth — it is authenticated by its HMAC signature and routed to a tenant
by the order notes Razorpay signs back to us — so it is mounted on its own router.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request

from app.billing import invoicing, payments, reconciliation
from app.compliance.audit import audit
from app.core.auth import CurrentTenant
from app.core.context import TenantContext
from app.core.logging import get_logger
from app.identity.rbac import Scoped
from app.metering.money import usd_to_nanos
from app.schemas.billing import (
    InvoiceGenerate,
    InvoiceOut,
    PaymentOut,
    ReconciliationOut,
    RefundCreate,
    TopupConfirm,
    TopupCreate,
    TopupOut,
)

log = get_logger(__name__)

billing_router = APIRouter()
invoices_router = APIRouter()
webhook_router = APIRouter()


@billing_router.post("/topups", response_model=TopupOut, status_code=201)
async def create_topup(
    tenant: Annotated[TenantContext, Scoped("billing:write")], payload: TopupCreate
) -> TopupOut:
    """Create a Razorpay order for a wallet top-up; the client opens checkout with the result."""
    out = await payments.create_topup(tenant.tenant_id, payload.amount_usd)
    await audit(
        tenant, "topup.create", resource_type="order", resource_id=out.order_id,
        context={"amount_usd": str(payload.amount_usd)},
    )
    return out


@billing_router.post("/topups/{order_id}/confirm", response_model=PaymentOut)
async def confirm_topup(
    tenant: Annotated[TenantContext, Scoped("billing:write")],
    order_id: str,
    payload: TopupConfirm,
) -> PaymentOut:
    """Verify the checkout callback signature and credit the wallet (idempotent)."""
    out = await payments.confirm_topup(
        tenant.tenant_id,
        order_id,
        razorpay_payment_id=payload.razorpay_payment_id,
        razorpay_signature=payload.razorpay_signature,
    )
    await audit(
        tenant, "topup.confirm", resource_type="payment", resource_id=out.id,
        context={"order_id": order_id, "status": out.status},
    )
    return out


@billing_router.get("/payments", response_model=list[PaymentOut])
async def list_payments(tenant: CurrentTenant) -> list[PaymentOut]:
    return await payments.list_payments(tenant.tenant_id)


@billing_router.post("/payments/{payment_id}/refund", response_model=PaymentOut)
async def refund_payment(
    tenant: Annotated[TenantContext, Scoped("billing:write")],
    payment_id: str,
    payload: RefundCreate,
) -> PaymentOut:
    """Refund all or part of a settled payment; the wallet is debited through the ledger."""
    amount = usd_to_nanos(payload.amount_usd) if payload.amount_usd is not None else None
    out = await payments.refund_payment(tenant.tenant_id, payment_id, amount)
    await audit(
        tenant, "payment.refund", resource_type="payment", resource_id=payment_id,
        context={"amount_usd": str(payload.amount_usd) if payload.amount_usd else "full"},
    )
    return out


@billing_router.get("/reconciliation", response_model=ReconciliationOut)
async def get_reconciliation(tenant: CurrentTenant) -> ReconciliationOut:
    """Ledger integrity + gateway drift for the tenant (raises an alert if beyond tolerance)."""
    return await reconciliation.reconcile(tenant.tenant_id)


@webhook_router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: Annotated[str | None, Header()] = None,
) -> dict:
    """Razorpay webhook — authenticated by HMAC signature, not by an API key.

    The raw body is verified before anything is parsed or applied, so a forged event never moves
    money. Returns 200 with ``handled`` so Razorpay does not retry a correctly-received event.
    """
    raw = await request.body()
    result = await payments.handle_webhook(raw, x_razorpay_signature or "")
    return result


@invoices_router.get("", response_model=list[InvoiceOut])
async def list_invoices(tenant: CurrentTenant) -> list[InvoiceOut]:
    return await invoicing.list_invoices(tenant.tenant_id)


@invoices_router.post("", response_model=InvoiceOut, status_code=201)
async def generate_invoice(tenant: CurrentTenant, payload: InvoiceGenerate) -> InvoiceOut:
    """Roll the period's usage ledger into one statement across the whole fleet."""
    return await invoicing.generate_invoice(
        tenant.tenant_id,
        period_start=payload.period_start,
        period_end=payload.period_end,
        status=payload.status,
    )


@invoices_router.get("/{invoice_id}", response_model=InvoiceOut)
async def get_invoice(tenant: CurrentTenant, invoice_id: str) -> InvoiceOut:
    return await invoicing.get_invoice(tenant.tenant_id, invoice_id)
