"""Spend service — the aggregation queries behind the unified spend view (Phase 3).

All numbers come from the append-only ``ledger_entry`` (the source of truth), never recomputed
from provider responses, so what the client sees is exactly what was accounted. Cost (provider
charge) and price (tenant pays) are reported side by side; in the Phase 3 BYO default they are
equal, and Phase 4's markup makes the gap the platform's margin.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from app.db.session import tenant_session
from app.metering.money import CURRENCY, format_usd
from app.models.agent import Agent
from app.models.ledger_entry import LedgerEntry
from app.models.wallet import Wallet
from app.schemas.metering import (
    AgentSpend,
    EventTypeSpend,
    SpendSummary,
    WalletOut,
)


async def spend_summary(
    tenant_id: str,
    *,
    run_id: str | None = None,
    agent_id: str | None = None,
    since: datetime | None = None,
) -> SpendSummary:
    """Totalled spend for the tenant, optionally narrowed to one run / agent / time window."""
    scope = "run" if run_id else ("agent" if agent_id else "tenant")
    scope_id = run_id or agent_id

    def _filtered(stmt):
        stmt = stmt.where(
            LedgerEntry.tenant_id == tenant_id, LedgerEntry.entry_type == "usage"
        )
        if run_id:
            stmt = stmt.where(LedgerEntry.run_id == run_id)
        if agent_id:
            stmt = stmt.where(LedgerEntry.agent_id == agent_id)
        if since:
            stmt = stmt.where(LedgerEntry.created_at >= since)
        return stmt

    async with tenant_session(tenant_id) as session:
        totals = (
            await session.execute(
                _filtered(
                    select(
                        func.count(),
                        func.coalesce(func.sum(LedgerEntry.cost_nanos), 0),
                        func.coalesce(func.sum(LedgerEntry.price_nanos), 0),
                    )
                )
            )
        ).one()
        rows = (
            await session.execute(
                _filtered(
                    select(
                        LedgerEntry.event_type,
                        func.count(),
                        func.coalesce(func.sum(LedgerEntry.cost_nanos), 0),
                        func.coalesce(func.sum(LedgerEntry.price_nanos), 0),
                    )
                ).group_by(LedgerEntry.event_type)
            )
        ).all()

    count, cost, price = int(totals[0]), int(totals[1]), int(totals[2])
    by_type = [
        EventTypeSpend(
            event_type=r[0],
            count=int(r[1]),
            cost_nanos=int(r[2]),
            price_nanos=int(r[3]),
            cost_usd=format_usd(int(r[2])),
            price_usd=format_usd(int(r[3])),
        )
        for r in sorted(rows, key=lambda r: r[0])
    ]
    return SpendSummary(
        currency=CURRENCY,
        scope=scope,
        scope_id=scope_id,
        period_start=since,
        event_count=count,
        cost_nanos=cost,
        price_nanos=price,
        cost_usd=format_usd(cost),
        price_usd=format_usd(price),
        by_event_type=by_type,
    )


async def spend_by_agent(tenant_id: str) -> list[AgentSpend]:
    """Per-agent rated spend — the data behind 'cost per agent'."""
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                select(
                    LedgerEntry.agent_id,
                    func.count(),
                    func.coalesce(func.sum(LedgerEntry.cost_nanos), 0),
                    func.coalesce(func.sum(LedgerEntry.price_nanos), 0),
                )
                .where(LedgerEntry.tenant_id == tenant_id, LedgerEntry.entry_type == "usage")
                .group_by(LedgerEntry.agent_id)
            )
        ).all()
        names = dict(
            (
                await session.execute(
                    select(Agent.id, Agent.name).where(Agent.tenant_id == tenant_id)
                )
            ).all()
        )

    out = [
        AgentSpend(
            agent_id=r[0],
            agent_name=names.get(r[0]) if r[0] else None,
            event_count=int(r[1]),
            cost_nanos=int(r[2]),
            price_nanos=int(r[3]),
            cost_usd=format_usd(int(r[2])),
            price_usd=format_usd(int(r[3])),
        )
        for r in rows
    ]
    out.sort(key=lambda a: a.price_nanos, reverse=True)
    return out


async def get_wallet(tenant_id: str) -> WalletOut:
    """The tenant's wallet balance (a zero wallet if none has been created yet)."""
    async with tenant_session(tenant_id) as session:
        wallet = (
            await session.execute(select(Wallet).where(Wallet.tenant_id == tenant_id))
        ).scalar_one_or_none()
        if wallet is None:
            return WalletOut(
                currency=CURRENCY, balance_nanos=0, balance_usd=format_usd(0), enforce_balance=False
            )
        return WalletOut(
            currency=wallet.currency,
            balance_nanos=wallet.balance_nanos,
            balance_usd=format_usd(wallet.balance_nanos),
            enforce_balance=wallet.enforce_balance,
        )
