"""Slack connector (MESSAGING capability).

Two tools modelled on the real Slack Web API, each gated by a distinct scope so the broker can
grant posting without granting reading (or vice versa):

* ``slack.post_message``  — scope ``chat:write``     (write to a channel)
* ``slack.list_messages`` — scope ``channels:read``  (read recent channel history)

Offline/deterministic: the handlers echo a believable response shaped like Slack's, and prove the
credential was used by surfacing the (non-secret) workspace from the credential metadata. A live
implementation replaces the handler bodies with ``AsyncWebClient`` calls using ``credential.secret``
as the bot token.
"""

from __future__ import annotations

from app.connectors.base import ConnectorSpec, ResolvedCredential, ToolResult, ToolSpec
from app.connectors.builtin import BuiltinConnector
from app.connectors.capabilities import Capability

SCOPE_WRITE = "chat:write"
SCOPE_READ = "channels:read"

_TOOLS = (
    ToolSpec(
        name="slack.post_message",
        title="Post a Slack message",
        description="Post a message to a Slack channel.",
        capability=Capability.MESSAGING,
        required_scope=SCOPE_WRITE,
        input_schema={
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel id or name, e.g. #support"},
                "text": {"type": "string", "description": "Message text"},
            },
            "required": ["channel", "text"],
        },
    ),
    ToolSpec(
        name="slack.list_messages",
        title="List recent Slack messages",
        description="Read recent messages from a Slack channel.",
        capability=Capability.MESSAGING,
        required_scope=SCOPE_READ,
        input_schema={
            "type": "object",
            "properties": {
                "channel": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["channel"],
        },
    ),
)


def _workspace(cred: ResolvedCredential | None) -> str:
    return (cred.metadata.get("workspace") if cred else None) or "dev-workspace"


async def _post_message(args: dict, cred: ResolvedCredential | None) -> ToolResult:
    channel = str(args.get("channel", ""))
    text = str(args.get("text", ""))
    return ToolResult(
        output={
            "ok": True,
            "workspace": _workspace(cred),
            "channel": channel,
            "ts": "1700000000.000100",
            "text": text,
        }
    )


async def _list_messages(args: dict, cred: ResolvedCredential | None) -> ToolResult:
    channel = str(args.get("channel", ""))
    return ToolResult(
        output={
            "ok": True,
            "workspace": _workspace(cred),
            "channel": channel,
            "messages": [
                {"user": "U123", "text": "Customer asked about a refund earlier."},
            ],
        }
    )


SPEC = ConnectorSpec(
    key="slack",
    name="Slack",
    description="Read and post messages in Slack workspaces.",
    capabilities=(Capability.MESSAGING,),
    auth_type="oauth",
    scopes=(SCOPE_WRITE, SCOPE_READ),
    tools=_TOOLS,
)


def build() -> BuiltinConnector:
    return BuiltinConnector(
        SPEC,
        {"slack.post_message": _post_message, "slack.list_messages": _list_messages},
    )
