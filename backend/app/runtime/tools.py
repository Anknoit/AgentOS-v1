"""Built-in tools for the Phase 1 agent runtime.

These are deterministic, offline stubs so the Support Desk template runs end to end with no
network or credentials. They are intentionally *not* real integrations — scoped, credentialed
connectors (Slack, CRM, MCP) arrive in Phase 2 behind the same ``Tool`` shape. The kernel meters
every tool call as a ``usage_event`` and logs it to the action log, so the accounting and audit
seams are exercised from day one.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

# A knowledge base the Support Desk agent can "retrieve" from, deterministically.
_KB: dict[str, str] = {
    "refund": "Refunds are processed within 5–7 business days to the original payment method.",
    "reset": "To reset your password, open Settings → Security → Reset password.",
    "hours": "Support is available Monday–Friday, 9am–6pm in your local time zone.",
    "shipping": "Standard shipping takes 3–5 business days; express takes 1–2.",
}


@dataclass
class ToolResult:
    output: dict
    # Billable quantity for metering (e.g. number of API calls); priced in Phase 3.
    quantity: int = 1
    unit: str = "calls"


ToolFn = Callable[[dict], Awaitable[ToolResult]]


async def kb_search(args: dict) -> ToolResult:
    """Look up the knowledge base for snippets relevant to the query (keyword match)."""
    query = str(args.get("query", "")).lower()
    hits = [text for key, text in _KB.items() if key in query]
    if not hits:
        # Fall back to the most generic answer so the agent always has something to ground on.
        hits = [_KB["hours"]]
    return ToolResult(output={"query": args.get("query", ""), "results": hits})


_REGISTRY: dict[str, ToolFn] = {
    "kb_search": kb_search,
}


def get_tool(name: str) -> ToolFn | None:
    return _REGISTRY.get(name)


def available_tools() -> list[str]:
    return sorted(_REGISTRY)
