"""The rating engine prices events exactly — on the providers' own numbers."""

from __future__ import annotations

from app.metering.money import format_usd, nanos_to_usd, usd_to_nanos
from app.metering.rating import rate_event
from app.services.ratecards import builtin_default_card


def test_model_call_matches_provider_formula():
    card = builtin_default_card()
    # gpt-4o-mini list price: $0.15 / 1M input, $0.60 / 1M output.
    rated = rate_event(
        card,
        event_type="model_call",
        model="gpt-4o-mini",
        input_tokens=1000,
        output_tokens=2000,
    )
    # provider charge = (0.15*1000 + 0.60*2000) / 1e6 = $0.00135
    assert rated.cost_nanos == 1_350_000
    assert nanos_to_usd(rated.cost_nanos) == nanos_to_usd(usd_to_nanos("0.00135"))
    # BYO default: no markup, so tenant price == provider cost (reconciles exactly).
    assert rated.price_nanos == rated.cost_nanos


def test_unknown_model_uses_default_rate():
    card = builtin_default_card()
    rated = rate_event(
        card, event_type="model_call", model="some-new-model", input_tokens=1_000_000
    )
    # __default__ input is $0.50 / 1M → $0.50 for 1M tokens.
    assert rated.cost_nanos == usd_to_nanos("0.50")


def test_tool_and_connector_fees():
    card = builtin_default_card()
    tool = rate_event(card, event_type="tool_call", tool_name="kb_search", quantity=1)
    assert tool.cost_nanos == usd_to_nanos("0.001")
    conn = rate_event(card, event_type="connector_call", connector_key="slack", quantity=1)
    assert conn.cost_nanos == usd_to_nanos("0.0005")


def test_markup_turns_cost_into_price():
    from app.metering.rating import RateCardData

    card = RateCardData(
        name="marginal",
        version=1,
        model_prices={"gpt-4o-mini": {"input": "0.15", "output": "0.60"}},
        markup_pct="20",
    )
    rated = rate_event(card, event_type="model_call", model="gpt-4o-mini", input_tokens=1_000_000)
    assert rated.cost_nanos == usd_to_nanos("0.15")
    assert rated.price_nanos == usd_to_nanos("0.18")  # +20%


def test_money_roundtrip_and_format():
    assert usd_to_nanos("1") == 1_000_000_000
    assert usd_to_nanos("0.000000001") == 1
    assert format_usd(1_350_000) == "$0.00135"
    assert format_usd(-2_000_000_000) == "-$2"
