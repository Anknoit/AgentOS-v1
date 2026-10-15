"""In-process managed execution of agent runs.

A run is a **managed job, not a request thread**: ``RunManager`` drives ``execute_run`` in a
background task and fans its events out to any number of subscribers. A WebSocket client can
disconnect (or never connect) and the run still completes server-side; a client that connects
late replays the events it missed, then follows live. This is the dev-fallback equivalent of the
Arq worker path — with Redis configured, the same kernel runs on a worker instead.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

from app.core.logging import get_logger

log = get_logger(__name__)

_DONE = object()


class _Channel:
    def __init__(self) -> None:
        self.history: list[dict] = []
        self.subscribers: set[asyncio.Queue] = set()
        self.done = False
        self.task: asyncio.Task | None = None

    def publish(self, event: dict) -> None:
        self.history.append(event)
        for q in list(self.subscribers):
            q.put_nowait(event)

    def finish(self) -> None:
        self.done = True
        for q in list(self.subscribers):
            q.put_nowait(_DONE)


class RunManager:
    def __init__(self) -> None:
        self._channels: dict[str, _Channel] = {}

    def start(self, run_id: str, gen_factory: Callable[[], AsyncIterator[dict]]) -> None:
        """Begin executing a run in the background.

        Skips if the run is already executing (so concurrent WS subscribers don't double-start),
        but a finished run can be started again — that is how ``resume`` re-enters a paused or
        failed run from its checkpoint.
        """
        if self.is_active(run_id):
            return
        ch = _Channel()
        self._channels[run_id] = ch

        async def _pump() -> None:
            try:
                async for event in gen_factory():
                    ch.publish(event)
            except Exception as exc:  # pragma: no cover - kernel already traps its own errors
                log.error("run.pump_error", run_id=run_id, error=str(exc))
                ch.publish({"type": "error", "run_id": run_id, "message": str(exc)})
            finally:
                ch.finish()

        ch.task = asyncio.create_task(_pump())

    async def subscribe(self, run_id: str) -> AsyncIterator[dict]:
        """Yield a run's events: replay what was missed, then follow live until done."""
        ch = self._channels.get(run_id)
        if ch is None:
            return
        q: asyncio.Queue = asyncio.Queue()
        replay = list(ch.history)  # snapshot; no await before registering the subscriber
        ch.subscribers.add(q)
        try:
            for event in replay:
                yield event
            if ch.done and q.empty():
                return
            while True:
                event = await q.get()
                if event is _DONE:
                    return
                yield event
        finally:
            ch.subscribers.discard(q)

    async def wait(self, run_id: str) -> None:
        ch = self._channels.get(run_id)
        if ch is not None and ch.task is not None:
            await ch.task

    def cancel(self, run_id: str) -> bool:
        """Request cancellation of an in-flight run's task. Returns True if one was cancelled."""
        ch = self._channels.get(run_id)
        if ch is not None and ch.task is not None and not ch.task.done():
            ch.task.cancel()
            return True
        return False

    def is_active(self, run_id: str) -> bool:
        ch = self._channels.get(run_id)
        return ch is not None and not ch.done


_manager: RunManager | None = None


def get_run_manager() -> RunManager:
    global _manager
    if _manager is None:
        _manager = RunManager()
    return _manager
