"""Generic HTTP connector (WEB capability) — the simple escape hatch.

``http.fetch`` performs an HTTP GET so an agent can reach an arbitrary web/JSON endpoint without a
bespoke connector. It is credential-optional: a bound credential's ``secret`` is sent as a bearer
token when present (for authenticated APIs), otherwise the request is anonymous. The client is
injectable so tests drive it over an in-memory transport with no real network.

For a full protocol-level integration with a third-party app, prefer the remote **MCP** connector
(``app.connectors.remote``); this one is for one-off REST/JSON reads.
"""

from __future__ import annotations

import httpx

from app.connectors.base import (
    ConnectorSpec,
    MCPSession,
    ResolvedCredential,
    ToolResult,
    ToolSpec,
)
from app.connectors.capabilities import Capability
from app.connectors.session import InProcessMCPSession

SCOPE_FETCH = "web:fetch"

_TOOLS = (
    ToolSpec(
        name="http.fetch",
        title="Fetch a URL",
        description="HTTP GET a URL and return status and body (text, truncated).",
        capability=Capability.WEB,
        required_scope=SCOPE_FETCH,
        input_schema={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    ),
)

SPEC = ConnectorSpec(
    key="http",
    name="HTTP",
    description="Fetch arbitrary web/JSON endpoints over HTTP GET.",
    capabilities=(Capability.WEB,),
    auth_type="none",
    scopes=(SCOPE_FETCH,),
    tools=_TOOLS,
)

_MAX_BODY = 8192


class HttpConnector:
    """Generic HTTP connector. ``client`` is injectable for hermetic tests."""

    spec = SPEC

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def session(self, credential: ResolvedCredential | None) -> MCPSession:
        async def _fetch(args: dict, cred: ResolvedCredential | None) -> ToolResult:
            url = str(args.get("url", ""))
            headers = {}
            if cred and cred.secret:
                headers["Authorization"] = f"Bearer {cred.secret}"
            client = self._client or httpx.AsyncClient(timeout=15.0)
            try:
                resp = await client.get(url, headers=headers)
                body = resp.text[:_MAX_BODY]
                return ToolResult(
                    output={"status": resp.status_code, "url": url, "body": body},
                    is_error=resp.status_code >= 400,
                )
            finally:
                if self._client is None:
                    await client.aclose()

        return InProcessMCPSession(self.spec, {"http.fetch": _fetch}, credential)


def build() -> HttpConnector:
    return HttpConnector()
