from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class Wallet(Base, TenantScopedMixin):
    """A tenant's balance — a **cached projection** of the append-only ledger (Phase 3).

    ``balance_nanos`` is kept in step with each ledger write (credits add, usage debits subtract)
    so credit control reads it in O(1); it can always be rebuilt by summing the ledger, which is
    the source of truth. In Phase 3 (BYO keys) there are no top-ups yet, so the balance simply
    tracks accrued spend as it goes negative, and ``enforce_balance`` is off — budgets, not the
    balance, gate work. Phase 4 adds top-ups and flips ``enforce_balance`` on for prepaid credit
    control. One wallet per tenant.
    """

    __tablename__ = "wallet"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_wallet_tenant"),)

    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    balance_nanos: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    # Funds held against in-flight work (Phase 4 reserve/hold). Available = balance - reserved;
    # credit control authorizes against *available* so concurrent actions can't each pass a check
    # that only one of them fits, then release the hold when the real debit lands.
    reserved_nanos: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    # When true (Phase 4), a billable action is refused if it would overdraw the available balance.
    enforce_balance: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
