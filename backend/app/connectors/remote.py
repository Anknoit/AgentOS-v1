"""Generic remote MCP connector — connect any third-party MCP server (Phase 2, build task 5).

This is the "seamless 3rd-party app" path. A tenant stores a credential for the ``mcp`` connector
whose metadata carries the server ``url`` (and whose secret is the server's bearer token, if any).
At call time the broker builds a ``RemoteMCPSession`` to that URL, runs the MCP handshake, and the
server's tools become callable — discovered live via ``tools/list`` — under the same scope
enforcement, metering, and audit as every built-in connector.

Because a generic server's tools are not known ahead of time, the connector's static spec carries
no tools and a single coarse scope, ``mcp:call``: granting the ``mcp`` connector authorises calling
its server's tools. Servers that emit AgentOS ``_meta`` on their tools can advertise a finer scope
per tool, which the broker will then require.
"""

from __future__ import annotations

from app.connectors.base import ConnectorSpec, MCPSession, ResolvedCredential
from app.connectors.capabilities import Capability
from app.connectors.session import RemoteMCPSession

SCOPE_CALL = "mcp:call"

SPEC = ConnectorSpec(
    key="mcp",
    name="MCP server",
    description="Connect a third-party Model Context Protocol server and call its tools.",
    capabilities=(Capability.WEB,),
    auth_type="oauth",
    scopes=(SCOPE_CALL,),
    tools=(),  # discovered live via tools/list
    transport="http",
)


class RemoteMCPConnector:
    """Connector whose tools live on a remote MCP server addressed by the bound credential."""

    spec = SPEC

    def session(self, credential: ResolvedCredential | None) -> MCPSession:
        if credential is None or not credential.metadata.get("url"):
            raise ValueError("the 'mcp' connector requires a credential with metadata.url")
        token = credential.secret
        headers = {"Authorization": f"Bearer {token}"} if token else None
        return RemoteMCPSession(credential.metadata["url"], headers=headers)


def build() -> RemoteMCPConnector:
    return RemoteMCPConnector()
