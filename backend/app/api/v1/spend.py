"""Spend, wallet, rate-card, budget, and alert endpoints (Phase 3).

The read side of the moat: accurate per-agent / per-run / per-period cost, the wallet balance,
the active pricing, the spend caps, and the alerts — the data behind the client's unified spend
view. Everything is tenant-scoped through :class:`CurrentTenant`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Response
from sqlalchemy import select

from app.core.auth import CurrentTenant
from app.db.session import tenant_session
from app.models.alert import Alert
from app.schemas.metering import (
    AgentSpend,
    AlertOut,
    BudgetCreate,
    BudgetOut,
    RateCardOut,
    SpendSummary,
    WalletOut,
)
from app.services import budgets as budgets_service
from app.services import ratecards as ratecards_service
from app.services import spend as spend_service

spend_router = APIRouter()
wallet_router = APIRouter()
ratecards_router = APIRouter()
budgets_router = APIRouter()
alerts_router = APIRouter()


@spend_router.get("", response_model=SpendSummary)
async def get_spend(
    tenant: CurrentTenant,
    run_id: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    since: Annotated[datetime | None, Query()] = None,
) -> SpendSummary:
    """Rated spend for the tenant, optionally narrowed to one run, agent, or time window."""
    return await spend_service.spend_summary(
        tenant.tenant_id, run_id=run_id, agent_id=agent_id, since=since
    )


@spend_router.get("/agents", response_model=list[AgentSpend])
async def get_spend_by_agent(tenant: CurrentTenant) -> list[AgentSpend]:
    """Cost per agent — the fleet spend breakdown."""
    return await spend_service.spend_by_agent(tenant.tenant_id)


@wallet_router.get("", response_model=WalletOut)
async def get_wallet(tenant: CurrentTenant) -> WalletOut:
    return await spend_service.get_wallet(tenant.tenant_id)


@ratecards_router.get("", response_model=list[RateCardOut])
async def list_rate_cards(tenant: CurrentTenant) -> list[RateCardOut]:
    cards = await ratecards_service.list_cards(tenant.tenant_id)
    return [RateCardOut.model_validate(c) for c in cards]


@budgets_router.get("", response_model=list[BudgetOut])
async def list_budgets(tenant: CurrentTenant) -> list[BudgetOut]:
    return await budgets_service.list_budgets(tenant.tenant_id)


@budgets_router.post("", response_model=BudgetOut, status_code=201)
async def create_budget(tenant: CurrentTenant, payload: BudgetCreate) -> BudgetOut:
    return await budgets_service.create_budget(tenant.tenant_id, payload)


@budgets_router.delete("/{budget_id}", status_code=204, response_class=Response)
async def delete_budget(tenant: CurrentTenant, budget_id: str) -> Response:
    await budgets_service.delete_budget(tenant.tenant_id, budget_id)
    return Response(status_code=204)


@alerts_router.get("", response_model=list[AlertOut])
async def list_alerts(
    tenant: CurrentTenant,
    run_id: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    limit: int = Query(default=100, le=1000),
) -> list[AlertOut]:
    async with tenant_session(tenant.tenant_id) as session:
        stmt = (
            select(Alert)
            .where(Alert.tenant_id == tenant.tenant_id)
            .order_by(Alert.created_at.desc())
            .limit(limit)
        )
        if run_id:
            stmt = stmt.where(Alert.run_id == run_id)
        if kind:
            stmt = stmt.where(Alert.kind == kind)
        rows = (await session.execute(stmt)).scalars().all()
        return [AlertOut.model_validate(r) for r in rows]
