"""The remote MCP wire path — connect a third-party MCP server over real JSON-RPC 2.0.

A fake MCP server is served in-process via an httpx ``MockTransport`` (no network), so the whole
Streamable-HTTP client — initialize handshake, ``tools/list`` discovery, ``tools/call`` — is
exercised exactly as it would be against a real server. This is the seam that makes a third-party
app pluggable: anything that speaks MCP shows up as callable tools.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.connectors.mcp import PROTOCOL_VERSION, StreamableHttpTransport
from app.connectors.session import RemoteMCPSession


def _fake_mcp_server(*, sse_for_list: bool = False):
    """A minimal spec-compliant MCP server over JSON-RPC 2.0."""

    def handler(request: httpx.Request) -> httpx.Response:
        msg = json.loads(request.content)
        method = msg.get("method")
        mid = msg.get("id")

        if method == "notifications/initialized":
            return httpx.Response(202)  # notification: no body
        if method == "initialize":
            # the client must advertise the protocol version it speaks
            assert msg["params"]["protocolVersion"] == PROTOCOL_VERSION
            return _json(mid, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-mcp", "version": "1.0"},
            })
        if method == "tools/list":
            result = {"tools": [{
                "name": "echo",
                "title": "Echo",
                "description": "Echo back the input text.",
                "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
                "_meta": {"capability": "web", "scope": "mcp:call"},
            }]}
            if sse_for_list:
                body = f"event: message\ndata: {json.dumps(_envelope(mid, result))}\n\n"
                return httpx.Response(
                    200, text=body, headers={"content-type": "text/event-stream"}
                )
            return _json(mid, result)
        if method == "tools/call":
            text = msg["params"]["arguments"].get("text", "")
            return _json(mid, {
                "content": [{"type": "text", "text": f"echo: {text}"}],
                "isError": False,
            })
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": mid,
                       "error": {"code": -32601, "message": "method not found"}}
        )

    return handler


def _envelope(mid, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _json(mid, result: dict) -> httpx.Response:
    return httpx.Response(200, json=_envelope(mid, result))


def _session(handler) -> RemoteMCPSession:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = StreamableHttpTransport("https://mcp.example.com/rpc", client=client)
    return RemoteMCPSession.from_transport(transport)


@pytest.mark.asyncio
async def test_initialize_and_discover_and_call():
    session = _session(_fake_mcp_server())
    info = await session.initialize()
    assert info["serverInfo"]["name"] == "fake-mcp"

    tools = await session.list_tools()
    assert [t.name for t in tools] == ["echo"]
    assert tools[0].required_scope == "mcp:call"

    result = await session.call_tool("echo", {"text": "hello"})
    assert result.is_error is False
    assert "echo: hello" in result.output["content"]
    await session.close()


@pytest.mark.asyncio
async def test_tools_list_over_sse_transport():
    # The server may reply as text/event-stream; the client must decode it the same way.
    session = _session(_fake_mcp_server(sse_for_list=True))
    await session.initialize()
    tools = await session.list_tools()
    assert [t.name for t in tools] == ["echo"]
    await session.close()
