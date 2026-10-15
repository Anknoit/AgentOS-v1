"""Model Context Protocol wire client (Phase 2, build task 2 — "MCP as the primary protocol").

This is a focused, spec-faithful MCP client for the **Streamable HTTP** transport. It implements
the parts of the protocol AgentOS needs to drive a third-party server as a connector:

* **JSON-RPC 2.0** request/response/notification framing (the MCP wire format);
* the **initialize handshake** with protocol-version and capability negotiation, followed by the
  ``notifications/initialized`` notification, exactly as the lifecycle spec requires;
* **``tools/list``** (discovery) and **``tools/call``** (invocation), with MCP's structured
  ``content`` / ``isError`` result shape decoded into our ``ToolResult``.

We deliberately keep this dependency-light (httpx only) rather than pulling the full MCP SDK: the
transport is abstracted behind ``Transport`` so the official SDK — or a stdio transport — can slot
in later without touching callers, and so tests can drive the real JSON-RPC path against an
in-process fake server over an httpx ``MockTransport`` (no network, fully hermetic).

Protocol revision targeted: ``2025-06-18``.
"""

from __future__ import annotations

import itertools
from typing import Any, Protocol

import httpx

from app.connectors.base import ToolResult, ToolSpec
from app.connectors.capabilities import Capability, parse_capability

PROTOCOL_VERSION = "2025-06-18"
JSONRPC_VERSION = "2.0"
CLIENT_INFO = {"name": "agentos", "version": "0.2.0"}


class MCPError(Exception):
    """A JSON-RPC error or a protocol violation from an MCP server."""

    def __init__(self, message: str, *, code: int | None = None, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


class Transport(Protocol):
    """Sends one JSON-RPC message, returns the decoded reply (None for notifications)."""

    async def send(self, message: dict) -> dict | None: ...
    async def close(self) -> None: ...


class StreamableHttpTransport:
    """MCP Streamable HTTP transport: POST JSON-RPC to the server endpoint.

    Supports both reply encodings the spec allows: a direct ``application/json`` body, and a
    ``text/event-stream`` SSE body carrying one JSON-RPC message per ``data:`` event (we read the
    first/terminal response event). The MCP ``Mcp-Session-Id`` header, when the server issues one
    on initialize, is echoed on subsequent requests to keep the logical session.
    """

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._url = url
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            **(headers or {}),
        }
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._session_id: str | None = None

    async def send(self, message: dict) -> dict | None:
        headers = dict(self._headers)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        resp = await self._client.post(self._url, json=message, headers=headers)
        resp.raise_for_status()
        if sid := resp.headers.get("mcp-session-id"):
            self._session_id = sid
        # Notifications (no "id") expect 202 Accepted with no body.
        if "id" not in message or resp.status_code == 202:
            return None
        ctype = resp.headers.get("content-type", "")
        if ctype.startswith("text/event-stream"):
            return _first_sse_json(resp.text)
        return resp.json()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _first_sse_json(body: str) -> dict | None:
    """Pull the first JSON-RPC payload out of an SSE stream body."""
    import json

    for line in body.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:"):].strip())
    return None


class MCPClient:
    """Drives one logical MCP session over a ``Transport`` using JSON-RPC 2.0."""

    def __init__(self, transport: Transport) -> None:
        self._t = transport
        self._ids = itertools.count(1)
        self._initialized = False

    async def _request(self, method: str, params: dict | None = None) -> Any:
        msg = {"jsonrpc": JSONRPC_VERSION, "id": next(self._ids), "method": method}
        if params is not None:
            msg["params"] = params
        reply = await self._t.send(msg)
        if reply is None:
            raise MCPError(f"no reply to request '{method}'")
        if "error" in reply:
            err = reply["error"] or {}
            raise MCPError(
                err.get("message", "mcp error"), code=err.get("code"), data=err.get("data")
            )
        return reply.get("result", {})

    async def _notify(self, method: str, params: dict | None = None) -> None:
        msg = {"jsonrpc": JSONRPC_VERSION, "method": method}
        if params is not None:
            msg["params"] = params
        await self._t.send(msg)

    async def initialize(self) -> dict:
        """Run the MCP lifecycle handshake and return the server's advertised info/capabilities."""
        result = await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "clientInfo": CLIENT_INFO,
            },
        )
        await self._notify("notifications/initialized")
        self._initialized = True
        return result

    async def list_tools(self) -> list[ToolSpec]:
        result = await self._request("tools/list")
        return [_tool_from_mcp(t) for t in result.get("tools", [])]

    async def call_tool(self, name: str, arguments: dict) -> ToolResult:
        result = await self._request("tools/call", {"name": name, "arguments": arguments})
        return _result_from_mcp(result)

    async def close(self) -> None:
        await self._t.close()


def _tool_from_mcp(t: dict) -> ToolSpec:
    meta = t.get("_meta") or {}
    cap = parse_capability(meta.get("capability", "")) or Capability.WEB
    return ToolSpec(
        name=t["name"],
        title=t.get("title", t["name"]),
        description=t.get("description", ""),
        capability=cap,
        required_scope=meta.get("scope", f"{cap.value}:use"),
        input_schema=t.get("inputSchema", {"type": "object"}),
    )


def _result_from_mcp(result: dict) -> ToolResult:
    """Decode MCP's ``{content: [...], isError, structuredContent}`` into a ToolResult."""
    structured = result.get("structuredContent")
    if structured is not None:
        output = structured if isinstance(structured, dict) else {"value": structured}
    else:
        texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        output = {"content": "\n".join(texts)} if texts else {"content": result.get("content", [])}
    return ToolResult(output=output, is_error=bool(result.get("isError", False)))
