"""Reconciliation — prove the ledger hangs together and surface drift (Phase 4).

Two independent checks, both reading only the append-only ledger (the source of truth):

1. **Wallet projection integrity.** The wallet balance must equal ``topups − refunds − usage_price``
   summed from the ledger. A non-zero ``balance_drift`` means the cached projection diverged from
   its ledger and should be rebuilt — the Phase 3 wallet-repair follow-up, now a live check.
2. **Gateway drift.** The USD credited by settled top-ups must match what the gateway actually
   charged (``gateway_amount_minor`` converted back to USD). Drift here means an FX or fee mismatch
   between what we billed the card and what we credited the wallet.

Drift beyond ``tolerance`` raises a ``reconciliation_drift`` alert so margin never silently leaks.
This is the mechanism the plan calls for comparing rated spend against providers' actual bills;
in BYO the provider charge *is* the rated cost, so the same machinery compares credited vs charged.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from app.db.session import tenant_session
from app.metering.anomaly import raise_alert
from app.metering.money import CURRENCY, format_usd
from app.models.ledger_entry import LedgerEntry
from app.models.payment import Payment
from app.models.wallet import Wallet
from app.schemas.billing import ReconciliationOut

# A nanodollar is sub-cent; allow a few nanos of rounding across a period before flagging drift.
DEFAULT_TOLERANCE_NANOS = 1_000  # $0.000001


async def _sum(session, tenant_id: str, entry_type: str, column) -> int:
    stmt = select(func.coalesce(func.sum(column), 0)).where(
        LedgerEntry.tenant_id == tenant_id, LedgerEntry.entry_type == entry_type
    )
    return int((await session.execute(stmt)).scalar_one())


async def reconcile(
    tenant_id: str,
    *,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    tolerance_nanos: int = DEFAULT_TOLERANCE_NANOS,
    alert: bool = True,
) -> ReconciliationOut:
    # The balance is cumulative, so the integrity identity is evaluated over all time (a period
    # subset can't balance). ``period_*`` are echoed for context only.
    async with tenant_session(tenant_id) as session:
        topups = await _sum(session, tenant_id, "topup", LedgerEntry.price_nanos)
        refunds = await _sum(session, tenant_id, "refund", LedgerEntry.price_nanos)
        usage_cost = await _sum(session, tenant_id, "usage", LedgerEntry.cost_nanos)
        usage_price = await _sum(session, tenant_id, "usage", LedgerEntry.price_nanos)

        wallet = (
            await session.execute(select(Wallet).where(Wallet.tenant_id == tenant_id))
        ).scalar_one_or_none()
        wallet_balance = wallet.balance_nanos if wallet else 0

        # What the gateway actually charged for settled top-ups, converted back to USD.
        gateway_charged = int(
            (
                await session.execute(
                    select(func.coalesce(func.sum(Payment.amount_nanos), 0)).where(
                        Payment.tenant_id == tenant_id,
                        Payment.ledger_entry_id.is_not(None),
                    )
                )
            ).scalar_one()
        )

    expected_balance = topups - refunds - usage_price
    balance_drift = wallet_balance - expected_balance
    gateway_drift = topups - gateway_charged
    within = abs(balance_drift) <= tolerance_nanos and abs(gateway_drift) <= tolerance_nanos

    if alert and not within:
        async with tenant_session(tenant_id) as session:
            await raise_alert(
                session,
                tenant_id=tenant_id,
                kind="reconciliation_drift",
                severity="critical",
                message=(
                    f"reconciliation drift: balance {format_usd(balance_drift)}, "
                    f"gateway {format_usd(gateway_drift)} (tolerance {format_usd(tolerance_nanos)})"
                ),
                context={
                    "balance_drift_nanos": balance_drift,
                    "gateway_drift_nanos": gateway_drift,
                    "tolerance_nanos": tolerance_nanos,
                },
                dedupe_per_run=False,
            )

    return ReconciliationOut(
        currency=CURRENCY,
        period_start=period_start,
        period_end=period_end,
        topups_nanos=topups,
        refunds_nanos=refunds,
        usage_cost_nanos=usage_cost,
        usage_price_nanos=usage_price,
        margin_nanos=usage_price - usage_cost,
        expected_balance_nanos=expected_balance,
        wallet_balance_nanos=wallet_balance,
        balance_drift_nanos=balance_drift,
        gateway_charged_nanos=gateway_charged,
        gateway_drift_nanos=gateway_drift,
        within_tolerance=within,
        tolerance_nanos=tolerance_nanos,
    )
