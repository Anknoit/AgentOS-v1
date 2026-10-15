from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class Payment(Base, TenantScopedMixin):
    """A wallet top-up through the payment gateway (Phase 4) — the settlement audit record.

    One row per Razorpay order. It is the durable truth of a money-in attempt and the anchor for
    reconciliation: the gateway's ``order_id`` is unique per tenant, so the checkout callback and
    the asynchronous webhook (which both report the same payment) converge on the same row and
    credit the wallet exactly once (``ledger_entry_id`` set under the row's lock).

    ``amount_nanos`` is the USD the wallet is credited; ``gateway_amount_minor`` /
    ``gateway_currency`` record what the gateway actually charged (e.g. cents, or paise at an FX
    rate) so a drift between the two is detectable. ``refunded_nanos`` tracks refunds against it.
    """

    __tablename__ = "payment"
    __table_args__ = (UniqueConstraint("tenant_id", "order_id", name="uq_payment_order"),)

    provider: Mapped[str] = mapped_column(String(32), default="razorpay", nullable=False)
    order_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    payment_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    # created -> paid | failed ; refunded when fully refunded; disputed on a chargeback.
    status: Mapped[str] = mapped_column(String(16), default="created", nullable=False)

    amount_nanos: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    gateway_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    gateway_currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)

    method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    signature_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ledger_entry_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    refunded_nanos: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    receipt: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
