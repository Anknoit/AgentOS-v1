"""Invoicing engine — one statement per tenant, line items rolled from the ledger (Phase 4).

An invoice is a *projection* of the append-only ledger over a period, never a recomputation from
provider responses, so the statement is exactly what was accounted. Usage entries are grouped by
agent and event type into line items; both provider ``cost`` and tenant ``price`` are totalled and
``margin = price - cost`` is recorded as an accounted quantity (the rate card's markup made real).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.db.session import tenant_session
from app.metering.money import CURRENCY, format_usd
from app.models.agent import Agent
from app.models.invoice import Invoice
from app.models.ledger_entry import LedgerEntry
from app.schemas.billing import InvoiceLine, InvoiceOut

log = get_logger(__name__)


def _to_out(inv: Invoice) -> InvoiceOut:
    lines = [InvoiceLine(**ln) for ln in (inv.line_items or [])]
    return InvoiceOut(
        id=inv.id,
        number=inv.number,
        status=inv.status,
        currency=inv.currency,
        period_start=inv.period_start,
        period_end=inv.period_end,
        issued_at=inv.issued_at,
        event_count=inv.event_count,
        cost_nanos=inv.cost_nanos,
        price_nanos=inv.price_nanos,
        margin_nanos=inv.margin_nanos,
        cost_usd=format_usd(inv.cost_nanos),
        price_usd=format_usd(inv.price_nanos),
        margin_usd=format_usd(inv.margin_nanos),
        total_usd=format_usd(inv.price_nanos),
        line_items=lines,
    )


async def generate_invoice(
    tenant_id: str,
    *,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    status: str = "issued",
) -> InvoiceOut:
    """Roll the period's usage ledger into one invoice across the whole fleet."""
    now = datetime.now(timezone.utc)
    period_end = period_end or now
    period_start = period_start or (period_end - timedelta(days=30))

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                select(
                    LedgerEntry.agent_id,
                    LedgerEntry.event_type,
                    func.count(),
                    func.coalesce(func.sum(LedgerEntry.cost_nanos), 0),
                    func.coalesce(func.sum(LedgerEntry.price_nanos), 0),
                )
                .where(
                    LedgerEntry.tenant_id == tenant_id,
                    LedgerEntry.entry_type == "usage",
                    LedgerEntry.created_at >= period_start,
                    LedgerEntry.created_at < period_end,
                )
                .group_by(LedgerEntry.agent_id, LedgerEntry.event_type)
            )
        ).all()
        names = dict(
            (
                await session.execute(
                    select(Agent.id, Agent.name).where(Agent.tenant_id == tenant_id)
                )
            ).all()
        )
        count = (
            await session.execute(
                select(func.count())
                .select_from(Invoice)
                .where(Invoice.tenant_id == tenant_id)
            )
        ).scalar_one()

        lines: list[dict] = []
        total_cost = total_price = total_events = 0
        for agent_id, event_type, n, cost, price in rows:
            n, cost, price = int(n), int(cost), int(price)
            total_cost += cost
            total_price += price
            total_events += n
            lines.append(
                {
                    "agent_id": agent_id,
                    "agent_name": names.get(agent_id) if agent_id else None,
                    "event_type": event_type,
                    "event_count": n,
                    "cost_nanos": cost,
                    "price_nanos": price,
                    "cost_usd": format_usd(cost),
                    "price_usd": format_usd(price),
                }
            )
        lines.sort(key=lambda ln: ln["price_nanos"], reverse=True)

        invoice = Invoice(
            tenant_id=tenant_id,
            number=f"INV-{count + 1:04d}",
            status=status,
            currency=CURRENCY,
            period_start=period_start,
            period_end=period_end,
            issued_at=now,
            event_count=total_events,
            cost_nanos=total_cost,
            price_nanos=total_price,
            margin_nanos=total_price - total_cost,
            line_items=lines,
            detail={},
        )
        session.add(invoice)
        await session.flush()
        out = _to_out(invoice)
    log.info(
        "invoice.generated",
        tenant_id=tenant_id,
        number=out.number,
        price_nanos=out.price_nanos,
        events=out.event_count,
    )
    return out


async def list_invoices(tenant_id: str) -> list[InvoiceOut]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                select(Invoice)
                .where(Invoice.tenant_id == tenant_id)
                .order_by(Invoice.issued_at.desc())
            )
        ).scalars().all()
        return [_to_out(r) for r in rows]


async def get_invoice(tenant_id: str, invoice_id: str) -> InvoiceOut:
    async with tenant_session(tenant_id) as session:
        inv = (
            await session.execute(
                select(Invoice).where(
                    Invoice.tenant_id == tenant_id, Invoice.id == invoice_id
                )
            )
        ).scalar_one_or_none()
        if inv is None:
            raise NotFoundError(f"invoice '{invoice_id}' not found")
        return _to_out(inv)
