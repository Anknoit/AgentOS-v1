"""Rate-card service — the built-in default prices and the active-card lookup.

The default card carries **real provider prices** (USD per 1M tokens) so AgentOS's rated spend
lands on the providers' own numbers, not an approximation — the Phase 3 accuracy bar. It is
seeded per tenant and is also the in-code fallback if a tenant has no card row, so rating always
has a card to price against.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.session import tenant_session
from app.metering.rating import RateCardData
from app.models.rate_card import RateCard

log = get_logger(__name__)

DEFAULT_CARD_NAME = "default"

# Provider list prices, USD per 1M tokens (cost). Kept close to public rate cards so rated spend
# reconciles against provider invoices within rounding. Extend as models are added.
DEFAULT_MODEL_PRICES: dict[str, dict[str, str]] = {
    "gpt-4o-mini": {"input": "0.15", "output": "0.60"},
    "gpt-4o": {"input": "2.50", "output": "10.00"},
    "gpt-4.1-mini": {"input": "0.40", "output": "1.60"},
    "gpt-4.1": {"input": "2.00", "output": "8.00"},
    "claude-haiku-4-5": {"input": "1.00", "output": "5.00"},
    "claude-sonnet-4-5": {"input": "3.00", "output": "15.00"},
    "__default__": {"input": "0.50", "output": "1.50"},
}
# Per-call platform fees for non-token work, USD per call.
DEFAULT_TOOL_FEES: dict[str, str] = {"__default__": "0.001"}
DEFAULT_CONNECTOR_FEES: dict[str, str] = {"__default__": "0.0005"}
# Phase 3 is BYO keys: price == cost, no markup. Phase 4 raises this to turn on margin.
DEFAULT_MARKUP_PCT = "0"


def builtin_default_card() -> RateCardData:
    return RateCardData(
        name=DEFAULT_CARD_NAME,
        version=1,
        model_prices=dict(DEFAULT_MODEL_PRICES),
        tool_fees=dict(DEFAULT_TOOL_FEES),
        connector_fees=dict(DEFAULT_CONNECTOR_FEES),
        markup_pct=DEFAULT_MARKUP_PCT,
    )


def _to_data(row: RateCard) -> RateCardData:
    return RateCardData(
        name=row.name,
        version=row.version,
        currency=row.currency,
        model_prices=dict(row.model_prices or {}),
        tool_fees=dict(row.tool_fees or {}),
        connector_fees=dict(row.connector_fees or {}),
        markup_pct=row.markup_pct or "0",
        card_id=row.id,
    )


async def get_active_card(tenant_id: str) -> RateCardData:
    """The tenant's active card (latest effective ``effective_at <= now``), or the built-in one."""
    now = datetime.now(timezone.utc)
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                select(RateCard)
                .where(
                    RateCard.tenant_id == tenant_id,
                    RateCard.is_active.is_(True),
                    RateCard.effective_at <= now,
                )
                .order_by(RateCard.effective_at.desc(), RateCard.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return builtin_default_card()
        return _to_data(row)


async def list_cards(tenant_id: str) -> list[RateCard]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                select(RateCard)
                .where(RateCard.tenant_id == tenant_id)
                .order_by(RateCard.effective_at.desc(), RateCard.version.desc())
            )
        ).scalars().all()
        return list(rows)


async def ensure_default_card(tenant_id: str) -> None:
    """Seed the default card for a tenant if they have none (idempotent)."""
    async with tenant_session(tenant_id) as session:
        existing = (
            await session.execute(
                select(RateCard).where(
                    RateCard.tenant_id == tenant_id, RateCard.name == DEFAULT_CARD_NAME
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return
        session.add(
            RateCard(
                tenant_id=tenant_id,
                name=DEFAULT_CARD_NAME,
                version=1,
                currency="USD",
                effective_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                is_active=True,
                model_prices=dict(DEFAULT_MODEL_PRICES),
                tool_fees=dict(DEFAULT_TOOL_FEES),
                connector_fees=dict(DEFAULT_CONNECTOR_FEES),
                markup_pct=DEFAULT_MARKUP_PCT,
            )
        )
    log.info("ratecard.seeded", tenant_id=tenant_id, card=DEFAULT_CARD_NAME)
