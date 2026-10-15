"""Budget service — create, list, and delete spend caps; project each one's live spend.

Budgets are the *policy*; enforcement lives in :class:`app.metering.credit.CreditController`,
which reads the same ledger these projections do. Listing a budget shows its current period spend
and remaining headroom so the client can render a gauge.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select

from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.db.session import tenant_session
from app.metering.credit import _period_start
from app.metering.money import format_usd, usd_to_nanos
from app.models.budget import Budget
from app.models.ledger_entry import LedgerEntry
from app.schemas.metering import BudgetCreate, BudgetOut

log = get_logger(__name__)


async def _period_spend(session, tenant_id: str, budget: Budget) -> int:
    start = _period_start(budget.period, datetime.now(timezone.utc))
    stmt = select(func.coalesce(func.sum(LedgerEntry.price_nanos), 0)).where(
        LedgerEntry.tenant_id == tenant_id, LedgerEntry.entry_type == "usage"
    )
    if budget.scope == "agent":
        stmt = stmt.where(LedgerEntry.agent_id == budget.scope_id)
    if start is not None:
        stmt = stmt.where(LedgerEntry.created_at >= start)
    return int((await session.execute(stmt)).scalar_one())


def _to_out(budget: Budget, spend_nanos: int) -> BudgetOut:
    return BudgetOut(
        id=budget.id,
        name=budget.name,
        scope=budget.scope,
        scope_id=budget.scope_id,
        period=budget.period,
        limit_nanos=budget.limit_nanos,
        limit_usd=format_usd(budget.limit_nanos),
        enforcement=budget.enforcement,
        is_active=budget.is_active,
        spend_nanos=spend_nanos,
        spend_usd=format_usd(spend_nanos),
        remaining_nanos=max(0, budget.limit_nanos - spend_nanos),
        created_at=budget.created_at,
    )


async def create_budget(tenant_id: str, payload: BudgetCreate) -> BudgetOut:
    budget = Budget(
        tenant_id=tenant_id,
        name=payload.name,
        scope=payload.scope,
        scope_id=payload.scope_id if payload.scope == "agent" else None,
        period=payload.period,
        limit_nanos=usd_to_nanos(payload.limit_usd),
        enforcement=payload.enforcement,
        is_active=True,
    )
    async with tenant_session(tenant_id) as session:
        session.add(budget)
        await session.flush()
        spend = await _period_spend(session, tenant_id, budget)
        out = _to_out(budget, spend)
    log.info(
        "budget.created", budget=budget.name, limit_nanos=budget.limit_nanos, scope=budget.scope
    )
    return out


async def list_budgets(tenant_id: str) -> list[BudgetOut]:
    async with tenant_session(tenant_id) as session:
        budgets = (
            await session.execute(
                select(Budget)
                .where(Budget.tenant_id == tenant_id)
                .order_by(Budget.created_at.desc())
            )
        ).scalars().all()
        return [_to_out(b, await _period_spend(session, tenant_id, b)) for b in budgets]


async def delete_budget(tenant_id: str, budget_id: str) -> None:
    async with tenant_session(tenant_id) as session:
        budget = (
            await session.execute(
                select(Budget).where(Budget.tenant_id == tenant_id, Budget.id == budget_id)
            )
        ).scalar_one_or_none()
        if budget is None:
            raise NotFoundError(f"budget '{budget_id}' not found")
        await session.delete(budget)
