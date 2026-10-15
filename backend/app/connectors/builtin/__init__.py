"""Built-in connectors — in-process MCP servers that ship with AgentOS.

Each built-in is a real, scoped connector (Slack, CRM, HTTP) with the exact ``MCPSession`` surface
a third-party server would present. They are **deterministic offline stubs**: no network, no real
credentials required to exercise the framework, so the whole connector path (discover → bind →
scope-check → decrypt credential → call → meter → audit) runs end to end in CI — the same
principle as the Phase 1 ``kb_search`` tool. Swapping a stub for a live API client is a change
inside one handler; nothing above it moves.
"""

from __future__ import annotations

from app.connectors.base import ConnectorSpec, ResolvedCredential
from app.connectors.session import Handler, InProcessMCPSession, MCPSession


class BuiltinConnector:
    """A connector whose tools are in-process async handlers."""

    def __init__(self, spec: ConnectorSpec, handlers: dict[str, Handler]) -> None:
        self.spec = spec
        self._handlers = handlers

    def session(self, credential: ResolvedCredential | None) -> MCPSession:
        return InProcessMCPSession(self.spec, self._handlers, credential)
