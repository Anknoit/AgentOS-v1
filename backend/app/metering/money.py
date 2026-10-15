"""Money as exact integers — the first rule of an accounting core.

Every monetary quantity in the ledger is stored and computed as an **integer number of
nanodollars** (1 USD = 1_000_000_000 nano). Integers are exact on both Postgres and the SQLite
dev-fallback (SQLite's ``NUMERIC`` affinity can silently round a float; an integer column never
does), and token prices are sub-cent — gpt-4o-mini input is $0.15 per 1M tokens, i.e. 150 nano
per token — so a coarser unit (cents, micros) would lose precision on a single token.

All arithmetic that turns a price into an amount goes through :class:`decimal.Decimal` and is
quantized to a whole nanodollar exactly once, here, so rounding is defined in one place.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

#: Nanodollars per US dollar. The ledger's atomic money unit.
NANOS_PER_USD = 1_000_000_000
CURRENCY = "USD"


def usd_to_nanos(amount: Decimal | str | int) -> int:
    """Convert a dollar amount to whole nanodollars (half-up at the nano)."""
    d = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    return int((d * NANOS_PER_USD).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def nanos_to_usd(nanos: int) -> Decimal:
    """Exact dollar value of a nanodollar amount."""
    return (Decimal(nanos) / NANOS_PER_USD).quantize(Decimal("0.000000001"))


def format_usd(nanos: int) -> str:
    """Human-readable dollars, trimmed — ``$0.00061440`` — for logs and the API."""
    d = nanos_to_usd(nanos).normalize()
    sign = "-" if d < 0 else ""
    return f"{sign}${abs(d):f}"
