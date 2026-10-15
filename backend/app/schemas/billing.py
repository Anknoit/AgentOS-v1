"""DTOs for settlement — top-ups, payments, invoices, and reconciliation (Phase 4).

Money crosses the API as the exact integer ``*_nanos`` plus a human ``*_usd`` string, the same
contract as the Phase 3 spend view. Amounts in are set in dollars (``amount_usd``).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TopupCreate(BaseModel):
    amount_usd: Decimal = Field(..., gt=0)


class TopupOut(BaseModel):
    """What the client needs to open Razorpay checkout for the created order."""

    payment_id: str  # our Payment row id
    order_id: str  # Razorpay order id
    key_id: str  # Razorpay public key for checkout
    amount_minor: int  # amount in the gateway's minor unit (paise/cents)
    gateway_currency: str
    amount_nanos: int  # USD the wallet will be credited on success
    amount_usd: str
    receipt: str | None = None


class TopupConfirm(BaseModel):
    """The checkout callback the client returns after a successful payment."""

    razorpay_payment_id: str
    razorpay_signature: str


class RefundCreate(BaseModel):
    amount_usd: Decimal | None = Field(default=None, gt=0)


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    order_id: str
    payment_id: str | None
    status: str
    amount_nanos: int
    currency: str
    gateway_amount_minor: int
    gateway_currency: str
    method: str | None
    signature_verified: bool
    refunded_nanos: int
    created_at: datetime


class InvoiceLine(BaseModel):
    agent_id: str | None
    agent_name: str | None
    event_type: str
    event_count: int
    cost_nanos: int
    price_nanos: int
    cost_usd: str
    price_usd: str


class InvoiceGenerate(BaseModel):
    period_start: datetime | None = None
    period_end: datetime | None = None
    status: Literal["draft", "issued"] = "issued"


class InvoiceOut(BaseModel):
    id: str
    number: str
    status: str
    currency: str
    period_start: datetime
    period_end: datetime
    issued_at: datetime
    event_count: int
    cost_nanos: int
    price_nanos: int
    margin_nanos: int
    cost_usd: str
    price_usd: str
    margin_usd: str
    total_usd: str
    line_items: list[InvoiceLine]


class ReconciliationOut(BaseModel):
    """Does the ledger hang together, and does rated cost match what the gateway moved?"""

    currency: str
    period_start: datetime | None
    period_end: datetime | None
    # money in (settled top-ups) vs money out (usage) and the resulting balance
    topups_nanos: int
    refunds_nanos: int
    usage_cost_nanos: int
    usage_price_nanos: int
    margin_nanos: int
    expected_balance_nanos: int  # topups - refunds - usage_price (ledger projection)
    wallet_balance_nanos: int  # the cached wallet balance
    balance_drift_nanos: int  # cached - projected; 0 means the projection is intact
    gateway_charged_nanos: int  # what Razorpay actually charged, converted back to USD
    gateway_drift_nanos: int  # credited top-ups vs gateway charges
    within_tolerance: bool
    tolerance_nanos: int


class WalletEnforcementUpdate(BaseModel):
    enforce_balance: bool
