"""Event bus seam (ADR-0002).

Metering is event-driven and decoupled from execution: billable actions publish onto a bus and
rating/ledger writes happen downstream (Phase 3). In Phase 0 the bus is an interface with an
in-process async implementation so the app boots with no broker. NATS (and later Kafka) plug in
behind the same ``EventBus`` protocol.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from app.core.logging import get_logger

log = get_logger(__name__)

Handler = Callable[[str, dict[str, Any]], Awaitable[None]]


class EventBus(Protocol):
    async def publish(self, subject: str, payload: dict[str, Any]) -> None: ...
    def subscribe(self, subject: str, handler: Handler) -> None: ...
    async def close(self) -> None: ...


class InProcessBus:
    """Fan-out to in-process async handlers. Fire-and-forget; good enough for dev/tests."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = {}

    def subscribe(self, subject: str, handler: Handler) -> None:
        self._handlers.setdefault(subject, []).append(handler)

    async def publish(self, subject: str, payload: dict[str, Any]) -> None:
        handlers = self._handlers.get(subject, [])
        if not handlers:
            return
        await asyncio.gather(*(h(subject, payload) for h in handlers), return_exceptions=True)

    async def close(self) -> None:  # noqa: D401 - nothing to tear down
        return None


_bus: EventBus | None = None


def get_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = InProcessBus()
    return _bus


def set_bus(bus: EventBus) -> None:
    global _bus
    _bus = bus
