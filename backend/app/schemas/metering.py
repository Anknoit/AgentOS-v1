"""DTOs for the spend view, wallet, rate cards, budgets, and alerts (Phase 3).

Money crosses the API as a pair: the exact integer ``*_nanos`` (so the client can sum without
rounding) and a human ``*_usd`` string for display. Budgets are *set* in dollars (``limit_usd``)
and stored in nanos.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EventTypeSpend(BaseModel):
    event_type: str
    count: int
    cost_nanos: int
    price_nanos: int
    cost_usd: str
    price_usd: str


class SpendSummary(BaseModel):
    currency: str
    scope: str  # "tenant" | "run" | "agent"
    scope_id: str | None = None
    period_start: datetime | None = None
    event_count: int
    cost_nanos: int
    price_nanos: int
    cost_usd: str
    price_usd: str
    by_event_type: list[EventTypeSpend]


class AgentSpend(BaseModel):
    agent_id: str | None
    agent_name: str | None
    event_count: int
    cost_nanos: int
    price_nanos: int
    cost_usd: str
    price_usd: str


class WalletOut(BaseModel):
    currency: str
    balance_nanos: int
    balance_usd: str
    # Phase 4: funds held against in-flight work, and what's actually spendable.
    reserved_nanos: int = 0
    available_nanos: int = 0
    available_usd: str = "$0"
    enforce_balance: bool


class RateCardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    version: int
    currency: str
    effective_at: datetime
    is_active: bool
    model_prices: dict
    tool_fees: dict
    connector_fees: dict
    markup_pct: str


class BudgetCreate(BaseModel):
    name: str = Field(default="budget", max_length=64)
    scope: Literal["tenant", "agent"] = "tenant"
    scope_id: str | None = None
    period: Literal["total", "daily", "monthly"] = "total"
    limit_usd: Decimal = Field(..., gt=0)
    enforcement: Literal["soft", "hard"] = "hard"


class BudgetOut(BaseModel):
    id: str
    name: str
    scope: str
    scope_id: str | None
    period: str
    limit_nanos: int
    limit_usd: str
    enforcement: str
    is_active: bool
    spend_nanos: int
    spend_usd: str
    remaining_nanos: int
    created_at: datetime


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    severity: str
    message: str
    run_id: str | None
    agent_id: str | None
    context: dict
    created_at: datetime
