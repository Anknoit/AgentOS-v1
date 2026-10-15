"""Wallet money movements — credits, refunds, and reserve/hold, all through the ledger (Phase 4).

Every change to a balance is a ledger write first; the ``wallet`` row is the cached projection
(Phase 3's rule, now extended to money-in). A non-usage movement (``topup`` / ``refund`` /
``adjustment``) is **idempotent on ``(tenant_id, ref)``** — the gateway reference — so the checkout
callback and the webhook, which report the same payment, move the balance at most once.

Reserve/hold closes the Phase 3 residual risk: credit control reserves an estimate against
*available* balance (balance − reserved) before an action and the real debit releases it, so a
burst of concurrent actions can't each pass a check that only one of them fits. The wallet row is
the serialization point (the enclosing ``session.begin`` holds a write lock on it), which also
closes the concurrent-debit race.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.metering.money import CURRENCY
from app.models.ledger_entry import LedgerEntry
from app.models.wallet import Wallet

log = get_logger(__name__)


async def get_or_create_wallet(session: AsyncSession, tenant_id: str) -> Wallet:
    wallet = (
        await session.execute(select(Wallet).where(Wallet.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if wallet is None:
        wallet = Wallet(tenant_id=tenant_id, currency=CURRENCY, balance_nanos=0, reserved_nanos=0)
        session.add(wallet)
        await session.flush()
    return wallet


async def post_movement(
    session: AsyncSession,
    *,
    tenant_id: str,
    amount_nanos: int,
    entry_type: str,
    ref: str,
    provider: str = "razorpay",
    sign: int = 1,
    detail: dict | None = None,
    enable_enforce: bool = False,
) -> LedgerEntry | None:
    """Post a non-usage ledger movement and update the wallet, idempotent on ``ref``.

    ``sign`` is +1 for a credit (top-up: balance rises) or −1 for a debit (refund: balance falls).
    Returns the new entry, or ``None`` if ``ref`` was already posted (the balance is untouched on a
    replay). Runs inside the caller's transaction so the ledger write and the balance update commit
    together. Set ``enable_enforce`` to flip prepaid credit control on with the first top-up.
    """
    existing = (
        await session.execute(
            select(LedgerEntry).where(
                LedgerEntry.tenant_id == tenant_id, LedgerEntry.ref == ref
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return None

    entry = LedgerEntry(
        tenant_id=tenant_id,
        entry_type=entry_type,
        ref=ref,
        event_type=entry_type,
        provider=provider,
        quantity=1,
        cost_nanos=amount_nanos,
        price_nanos=amount_nanos,
        currency=CURRENCY,
        detail=detail or {},
    )
    session.add(entry)
    await session.flush()

    wallet = await get_or_create_wallet(session, tenant_id)
    wallet.balance_nanos = wallet.balance_nanos + sign * amount_nanos
    if enable_enforce:
        wallet.enforce_balance = True
    log.info(
        "wallet.movement",
        tenant_id=tenant_id,
        entry_type=entry_type,
        amount_nanos=amount_nanos,
        sign=sign,
        balance_nanos=wallet.balance_nanos,
    )
    return entry


async def adjust_reserved(session: AsyncSession, tenant_id: str, delta_nanos: int) -> None:
    """Add (hold) or subtract (release) reserved funds; reserved never goes below zero."""
    wallet = await get_or_create_wallet(session, tenant_id)
    wallet.reserved_nanos = max(0, wallet.reserved_nanos + delta_nanos)
