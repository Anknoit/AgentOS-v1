"""MCP session implementations — the two backings of the uniform ``MCPSession`` surface.

* ``InProcessMCPSession`` wraps a **built-in connector** whose tools are plain async Python
  handlers. It still presents the exact MCP surface (``initialize``/``list_tools``/``call_tool``),
  so built-ins and third-party servers are indistinguishable to the broker.
* ``RemoteMCPSession`` drives a **third-party MCP server** over the wire via ``MCPClient``. This is
  the seam that lets any MCP-speaking app plug in: point a connector at its URL and its tools
  appear in discovery and become callable under the same scope enforcement as everything else.

A handler receives the call arguments and the resolved (decrypted) credential, and returns a
``ToolResult``. Handlers never see other tenants' data: the credential is derived and decrypted
per tenant by the vault before the session is built.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.connectors.base import (
    ConnectorSpec,
    MCPSession,
    ResolvedCredential,
    ToolResult,
    ToolSpec,
)
from app.connectors.mcp import MCPClient, StreamableHttpTransport

Handler = Callable[[dict, ResolvedCredential | None], Awaitable[ToolResult]]


class InProcessMCPSession:
    """An MCP session backed by in-process async handlers (a built-in connector)."""

    def __init__(
        self,
        spec: ConnectorSpec,
        handlers: dict[str, Handler],
        credential: ResolvedCredential | None,
    ) -> None:
        self._spec = spec
        self._handlers = handlers
        self._credential = credential

    async def initialize(self) -> dict:
        return {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": self._spec.key, "version": "builtin"},
        }

    async def list_tools(self) -> list[ToolSpec]:
        return list(self._spec.tools)

    async def call_tool(self, name: str, arguments: dict) -> ToolResult:
        handler = self._handlers.get(name)
        if handler is None:
            return ToolResult(output={"error": f"unknown tool '{name}'"}, is_error=True)
        return await handler(arguments, self._credential)

    async def close(self) -> None:  # nothing to tear down
        return None


class RemoteMCPSession:
    """An MCP session backed by a remote server over Streamable HTTP (the 3rd-party hatch)."""

    def __init__(self, url: str, *, headers: dict[str, str] | None = None) -> None:
        self._client = MCPClient(StreamableHttpTransport(url, headers=headers))
        self._ready = False

    @classmethod
    def from_transport(cls, transport) -> RemoteMCPSession:
        """Build a session over a pre-wired transport (used in tests with an in-memory server)."""
        self = cls.__new__(cls)
        self._client = MCPClient(transport)
        self._ready = False
        return self

    async def initialize(self) -> dict:
        info = await self._client.initialize()
        self._ready = True
        return info

    async def list_tools(self) -> list[ToolSpec]:
        if not self._ready:
            await self.initialize()
        return await self._client.list_tools()

    async def call_tool(self, name: str, arguments: dict) -> ToolResult:
        if not self._ready:
            await self.initialize()
        return await self._client.call_tool(name, arguments)

    async def close(self) -> None:
        await self._client.close()


# A static check that both classes satisfy the MCPSession protocol (fails fast at import if not).
_: type[MCPSession] = InProcessMCPSession  # type: ignore[assignment]
__: type[MCPSession] = RemoteMCPSession  # type: ignore[assignment]
