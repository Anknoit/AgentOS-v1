"""Connector + tool specifications and the uniform MCP session surface (Phase 2, build task 2).

Everything an agent can touch — a built-in connector or a third-party app — is modelled as an
**MCP server** exposing **tools**. This module defines the vocabulary:

* ``ToolSpec`` — one callable tool, described the way MCP's ``tools/list`` describes it: a name,
  a human title, a description, and a **JSON Schema** for its arguments. We add two AgentOS-native
  fields the broker enforces: the ``capability`` the tool belongs to and the ``required_scope``.
* ``ConnectorSpec`` — static metadata for a connector (its key, the capabilities it provides, its
  auth type, the scopes it defines, and its tools). This is what the registry lists and the UI
  renders.
* ``MCPSession`` — the single runtime surface for *calling* a connector, mirroring MCP exactly:
  ``initialize → list_tools → call_tool``. Built-in connectors back it in-process; third-party
  apps back it with a JSON-RPC client over HTTP. The broker only ever sees an ``MCPSession``, so
  the enforcement path is identical whoever is on the other end.

``ToolResult`` matches the Phase 1 built-in-tool shape so the kernel meters a connector call the
same way it meters ``kb_search``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.connectors.capabilities import Capability


@dataclass(frozen=True)
class ToolSpec:
    """One connector tool, described MCP-style plus the AgentOS capability/scope it requires."""

    name: str  # qualified, e.g. "slack.post_message"
    title: str
    description: str
    capability: Capability
    required_scope: str
    input_schema: dict = field(default_factory=dict)  # JSON Schema (MCP ``inputSchema``)

    def mcp_dict(self) -> dict:
        """Render as an MCP ``tools/list`` entry (what a remote server would return)."""
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema or {"type": "object"},
            # AgentOS extension surfaced under _meta, per MCP's extensibility guidance.
            "_meta": {"capability": self.capability.value, "scope": self.required_scope},
        }


@dataclass(frozen=True)
class ConnectorSpec:
    """Static, discoverable metadata for a connector."""

    key: str  # stable id, e.g. "slack"
    name: str
    description: str
    capabilities: tuple[Capability, ...]
    auth_type: str  # "oauth" | "api_key" | "none"
    scopes: tuple[str, ...]  # every scope this connector defines
    tools: tuple[ToolSpec, ...]
    transport: str = "inprocess"  # "inprocess" (built-in) | "http" (remote MCP server)

    def tool(self, name: str) -> ToolSpec | None:
        return next((t for t in self.tools if t.name == name), None)


@dataclass(frozen=True)
class ToolResult:
    """The outcome of a tool call. ``quantity``/``unit`` feed metering (priced in Phase 3)."""

    output: dict
    quantity: int = 1
    unit: str = "calls"
    is_error: bool = False


@dataclass(frozen=True)
class ResolvedCredential:
    """A decrypted credential handed to a connector at call time — never logged, never persisted.

    ``secret`` is the raw token/key; ``metadata`` carries non-secret context (account id, base
    URL, granted scopes) the connector needs to make the call.
    """

    connector_key: str
    auth_type: str
    secret: str
    metadata: dict = field(default_factory=dict)


@runtime_checkable
class MCPSession(Protocol):
    """The uniform MCP surface the broker calls. In-process or remote, the contract is identical."""

    async def initialize(self) -> dict: ...
    async def list_tools(self) -> list[ToolSpec]: ...
    async def call_tool(self, name: str, arguments: dict) -> ToolResult: ...
    async def close(self) -> None: ...


@runtime_checkable
class Connector(Protocol):
    """A registered connector: its spec, plus a factory for an MCP session bound to a credential."""

    spec: ConnectorSpec

    def session(self, credential: ResolvedCredential | None) -> MCPSession: ...
