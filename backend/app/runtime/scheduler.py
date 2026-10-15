"""Fair, back-pressured run admission (Phase 5, build task 1).

Horizontal scaling starts with not letting one tenant's burst consume the whole box. The
:class:`FairScheduler` is a **fair semaphore** over run execution with two limits:

* a **global** in-flight cap — backpressure; beyond it, new runs wait rather than pile on;
* a **per-tenant** cap — so a single noisy tenant holds at most its share of slots and can never
  starve the others (with ``max=8`` and ``per_tenant=4``, one tenant can hold ≤ 4, leaving ≥ 4).

Waiters that can't be admitted immediately are queued per tenant and released **round-robin**, so
tenants take turns rather than being served first-come-first-served (which would let a flood from
one tenant jump the queue). In the in-process runtime this gates ``RunManager``; on the Arq path
the same intent is expressed by partitioning the queue per tenant (``queue:<tenant_id>``). The
distributed backend changes; this admission contract does not.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from app.config.settings import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


class FairScheduler:
    def __init__(self, *, max_concurrency: int, per_tenant_concurrency: int) -> None:
        self._max = max(1, max_concurrency)
        self._per_tenant = max(1, per_tenant_concurrency)
        self._running_total = 0
        self._running: dict[str, int] = defaultdict(int)
        self._waiters: dict[str, deque[asyncio.Future]] = {}
        self._rr: deque[str] = deque()  # tenants that currently have waiters, round-robin order

    # ---- public API ----
    @asynccontextmanager
    async def slot(self, tenant_id: str):
        """Hold one execution slot for ``tenant_id`` (waiting fairly if at capacity)."""
        await self._acquire(tenant_id)
        try:
            yield
        finally:
            self._release(tenant_id)

    def stats(self) -> dict:
        return {
            "max_concurrency": self._max,
            "per_tenant_concurrency": self._per_tenant,
            "running_total": self._running_total,
            "running_by_tenant": {k: v for k, v in self._running.items() if v},
            "waiting_by_tenant": {k: len(q) for k, q in self._waiters.items() if q},
        }

    def running(self, tenant_id: str) -> int:
        return self._running.get(tenant_id, 0)

    def waiting(self, tenant_id: str) -> int:
        q = self._waiters.get(tenant_id)
        return len(q) if q else 0

    # ---- internals ----
    def _can_admit(self, tenant_id: str) -> bool:
        return self._running_total < self._max and self._running[tenant_id] < self._per_tenant

    def _reserve(self, tenant_id: str) -> None:
        self._running_total += 1
        self._running[tenant_id] += 1

    async def _acquire(self, tenant_id: str) -> None:
        # Fast path: capacity available and no one else is waiting fairly ahead of us.
        if not self._waiters.get(tenant_id) and self._can_admit(tenant_id):
            self._reserve(tenant_id)
            return
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        q = self._waiters.setdefault(tenant_id, deque())
        if not q and tenant_id not in self._rr:
            self._rr.append(tenant_id)
        q.append(fut)
        # In case capacity is already free (e.g. only per-tenant pressure cleared), try now.
        self._dispatch()
        await fut  # resolved once the dispatcher has reserved our slot

    def _release(self, tenant_id: str) -> None:
        self._running_total = max(0, self._running_total - 1)
        self._running[tenant_id] = max(0, self._running[tenant_id] - 1)
        self._dispatch()

    def _dispatch(self) -> None:
        """Wake queued waiters round-robin while capacity allows."""
        while self._running_total < self._max:
            tenant = self._next_eligible()
            if tenant is None:
                return
            q = self._waiters[tenant]
            fut = q.popleft()
            self._reserve(tenant)
            if not q:
                self._waiters.pop(tenant, None)
                self._drop_from_rr(tenant)
            if not fut.done():
                fut.set_result(None)
            else:  # waiter was cancelled before we got here — give the slot back
                self._release(tenant)

    def _next_eligible(self) -> str | None:
        """Round-robin the tenants with waiters; return one under its per-tenant cap, or None."""
        for _ in range(len(self._rr)):
            tenant = self._rr[0]
            self._rr.rotate(-1)  # examined tenant moves to the back (fair rotation)
            q = self._waiters.get(tenant)
            if not q:
                self._drop_from_rr(tenant)
                continue
            if self._running[tenant] < self._per_tenant:
                return tenant
        return None

    def _drop_from_rr(self, tenant_id: str) -> None:
        try:
            self._rr.remove(tenant_id)
        except ValueError:
            pass


_scheduler: FairScheduler | None = None


def get_scheduler() -> FairScheduler:
    global _scheduler
    if _scheduler is None:
        s = get_settings()
        _scheduler = FairScheduler(
            max_concurrency=s.run_max_concurrency,
            per_tenant_concurrency=s.run_per_tenant_concurrency,
        )
    return _scheduler


def set_scheduler(scheduler: FairScheduler | None) -> None:
    global _scheduler
    _scheduler = scheduler
