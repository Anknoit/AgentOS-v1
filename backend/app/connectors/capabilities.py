"""Capability taxonomy (Phase 2, build task 1).

A **capability** is the typed kind of real-world system an agent may touch. Phase 2 ships three
(voice is deferred to Phase 5). Capabilities are the coarse grant an ``agent_version`` makes;
**scopes** are the fine-grained permission within a connector (e.g. ``chat:write``). The runtime
grants an agent only the capabilities *and* scopes its version declares — nothing ambient.

Keeping this a small closed vocabulary (rather than free-form strings) means the UI can render a
permission matrix, and the broker can reason about "this tool needs the MESSAGING capability and
the ``chat:write`` scope" uniformly across built-in and third-party MCP connectors.
"""

from __future__ import annotations

from enum import Enum


class Capability(str, Enum):
    """The kinds of system an agent can be granted access to."""

    MESSAGING = "messaging"  # Slack, email, chat — send/read messages
    DATA = "data"            # CRM, databases, records — query/mutate structured data
    WEB = "web"              # HTTP fetch, search, generic MCP servers — reach the open web
    # VOICE = "voice"        # deferred to Phase 5 (telephony subsystem)


ALL_CAPABILITIES: tuple[Capability, ...] = (
    Capability.MESSAGING,
    Capability.DATA,
    Capability.WEB,
)


def parse_capability(value: str) -> Capability | None:
    try:
        return Capability(value)
    except ValueError:
        return None
