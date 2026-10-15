"""Connector registry (Phase 2, build task 2).

A single process-wide registry of connectors so the runtime and the API can **discover** what is
available (``GET /v1/connectors``) and the broker can **resolve** a connector by key at call time.
Registration is uniform whether a connector is built-in (in-process MCP) or remote (a third-party
MCP server), because both satisfy the ``Connector`` protocol. Third-party servers register the
same way — point the generic ``mcp`` connector at them via a credential, or add a dedicated
``ConnectorSpec`` — so the catalogue grows without touching the runtime.
"""

from __future__ import annotations

from app.connectors import remote
from app.connectors.base import Connector, ConnectorSpec, ToolSpec
from app.connectors.builtin import crm, http, slack


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, Connector] = {}

    def register(self, connector: Connector) -> None:
        self._connectors[connector.spec.key] = connector

    def get(self, key: str) -> Connector | None:
        return self._connectors.get(key)

    def specs(self) -> list[ConnectorSpec]:
        return [c.spec for c in self._connectors.values()]

    def keys(self) -> list[str]:
        return sorted(self._connectors)

    def find_tool(self, qualified_name: str) -> tuple[ConnectorSpec, ToolSpec] | None:
        """Resolve a qualified tool name (``connector.tool``) to its connector + static spec."""
        for c in self._connectors.values():
            tool = c.spec.tool(qualified_name)
            if tool is not None:
                return c.spec, tool
        return None


def _build_default_registry() -> ConnectorRegistry:
    reg = ConnectorRegistry()
    reg.register(slack.build())
    reg.register(crm.build())
    reg.register(http.build())
    reg.register(remote.build())
    return reg


_registry: ConnectorRegistry | None = None


def get_registry() -> ConnectorRegistry:
    global _registry
    if _registry is None:
        _registry = _build_default_registry()
    return _registry


def set_registry(registry: ConnectorRegistry) -> None:
    global _registry
    _registry = registry
