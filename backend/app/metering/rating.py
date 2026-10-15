"""Rating engine — price one usage event against a versioned rate card (the telecom pattern).

A :class:`RateCardData` is the priced view of an ``agent`` fleet's costs: per-model token prices,
per-tool and per-connector call fees, and a platform markup — each carrying both a **cost** (what
the provider charges) and a **price** (what the tenant pays). In Phase 3 (BYO keys) the default
card sets ``price == cost`` (zero markup); Phase 4 turns margin on by raising ``price`` above
``cost``, and the ledger accounts the difference.

Rating is pure and deterministic: ``(card, event) -> Rated``. Given the same inputs it always
yields the same nanodollar amounts, so re-rating a replayed event can never drift — the exactly-
once guarantee the whole moat rests on. All money math runs through :mod:`app.metering.money`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.metering.money import CURRENCY, usd_to_nanos

DEFAULT_KEY = "__default__"


@dataclass(frozen=True)
class RateCardData:
    """A parsed, priceable rate card — the same shape whether it comes from the DB or the
    built-in default. Prices are USD-per-1M-tokens (models) or USD-per-call (tools/connectors),
    stored as strings so they are exact.
    """

    name: str
    version: int
    currency: str = CURRENCY
    # model -> {"input": cost/1M, "output": cost/1M}
    model_prices: dict[str, dict[str, str]] = field(default_factory=dict)
    tool_fees: dict[str, str] = field(default_factory=dict)  # tool -> cost/call
    connector_fees: dict[str, str] = field(default_factory=dict)  # connector -> cost/call
    # Markup applied to cost to get price (tenant-facing). 0 => pass-through (BYO, Phase 3).
    markup_pct: str = "0"
    card_id: str | None = None

    def _model(self, model: str | None) -> dict[str, str]:
        return self.model_prices.get(model or "", self.model_prices.get(DEFAULT_KEY, {}))

    def _tool(self, tool: str | None) -> str:
        return self.tool_fees.get(tool or "", self.tool_fees.get(DEFAULT_KEY, "0"))

    def _connector(self, connector: str | None) -> str:
        return self.connector_fees.get(connector or "", self.connector_fees.get(DEFAULT_KEY, "0"))


@dataclass(frozen=True)
class Rated:
    """The priced result for one event: provider cost and tenant price, both in nanodollars."""

    cost_nanos: int
    price_nanos: int
    currency: str
    detail: dict


def _with_markup(cost: Decimal, markup_pct: str) -> Decimal:
    return cost * (Decimal(1) + Decimal(markup_pct) / Decimal(100))


def rate_event(
    card: RateCardData,
    *,
    event_type: str,
    model: str | None = None,
    provider: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    quantity: int = 1,
    connector_key: str | None = None,
    tool_name: str | None = None,
) -> Rated:
    """Price one usage event. ``cost`` is the provider charge; ``price`` is cost × (1 + markup)."""
    detail: dict = {"rate_card": card.name, "rate_card_version": card.version}

    if event_type == "model_call":
        prices = card._model(model)
        in_rate = Decimal(prices.get("input", "0"))
        out_rate = Decimal(prices.get("output", "0"))
        cost = (in_rate * input_tokens + out_rate * output_tokens) / Decimal(1_000_000)
        detail.update(
            kind="model_call",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_rate_per_1m=str(in_rate),
            output_rate_per_1m=str(out_rate),
        )
    elif event_type == "tool_call":
        per_call = Decimal(card._tool(tool_name or model))
        cost = per_call * quantity
        detail.update(kind="tool_call", tool=tool_name, per_call=str(per_call), quantity=quantity)
    elif event_type == "connector_call":
        per_call = Decimal(card._connector(connector_key or provider))
        cost = per_call * quantity
        detail.update(
            kind="connector_call",
            connector=connector_key or provider,
            per_call=str(per_call),
            quantity=quantity,
        )
    else:  # unknown event type rates to zero rather than guessing
        cost = Decimal(0)
        detail.update(kind=event_type, note="no rate rule; zero-rated")

    price = _with_markup(cost, card.markup_pct)
    cost_nanos = usd_to_nanos(cost)
    price_nanos = usd_to_nanos(price)
    detail.update(markup_pct=card.markup_pct, cost_nanos=cost_nanos, price_nanos=price_nanos)
    return Rated(
        cost_nanos=cost_nanos, price_nanos=price_nanos, currency=card.currency, detail=detail
    )
