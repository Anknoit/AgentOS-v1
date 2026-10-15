"""Fair, back-pressured run admission (Phase 5, build task 1).

Proves the three guarantees the scheduler exists for: a global in-flight cap (backpressure), a
per-tenant cap (so one tenant can't hold the whole box), and round-robin admission (so a flood from
one tenant can't starve another waiting behind it).
"""

from __future__ import annotations

import asyncio

from app.runtime.scheduler import FairScheduler


async def _settle() -> None:
    # Let pending scheduler callbacks and freshly-created tasks reach their await points.
    for _ in range(3):
        await asyncio.sleep(0)


async def test_global_concurrency_cap_applies_backpressure():
    sched = FairScheduler(max_concurrency=2, per_tenant_concurrency=5)
    gate = asyncio.Event()
    peak = 0
    live = 0

    async def job() -> None:
        nonlocal peak, live
        async with sched.slot("a"):
            live += 1
            peak = max(peak, live)
            await gate.wait()
            live -= 1

    tasks = [asyncio.create_task(job()) for _ in range(5)]
    await _settle()
    assert sched.stats()["running_total"] == 2  # only two admitted; the rest wait
    gate.set()
    await asyncio.gather(*tasks)
    assert peak == 2


async def test_per_tenant_cap_leaves_room_for_others():
    # Global room for 10, but each tenant may hold at most 2 — so a flood from "noisy" tops out at
    # 2 and "quiet" still gets in immediately (no starvation).
    sched = FairScheduler(max_concurrency=10, per_tenant_concurrency=2)
    gate = asyncio.Event()
    running: dict[str, int] = {"noisy": 0, "quiet": 0}
    peak: dict[str, int] = {"noisy": 0, "quiet": 0}

    async def job(t: str) -> None:
        async with sched.slot(t):
            running[t] += 1
            peak[t] = max(peak[t], running[t])
            await gate.wait()
            running[t] -= 1

    tasks = [asyncio.create_task(job("noisy")) for _ in range(8)]
    tasks += [asyncio.create_task(job("quiet")) for _ in range(2)]
    await _settle()
    assert sched.running("noisy") == 2  # capped despite 8 queued
    assert sched.running("quiet") == 2  # not starved
    gate.set()
    await asyncio.gather(*tasks)
    assert peak["noisy"] == 2


async def test_round_robin_is_fair_across_tenants():
    # One slot at a time; tenant "a" floods first, then "b" arrives. Round-robin admission means b
    # is served before a's remaining work drains, rather than last.
    sched = FairScheduler(max_concurrency=1, per_tenant_concurrency=1)
    order: list[str] = []
    gates: dict[str, asyncio.Event] = {k: asyncio.Event() for k in ("a1", "a2", "a3", "b1")}

    async def job(tenant: str, label: str) -> None:
        async with sched.slot(tenant):
            order.append(label)
            await gates[label].wait()

    asyncio.create_task(job("a", "a1"))
    await _settle()
    asyncio.create_task(job("a", "a2"))
    asyncio.create_task(job("a", "a3"))
    asyncio.create_task(job("b", "b1"))
    await _settle()

    assert order == ["a1"]  # only a1 admitted (cap 1)
    gates["a1"].set()
    await _settle()
    gates["a2"].set()
    await _settle()
    gates["b1"].set()
    await _settle()
    gates["a3"].set()
    await _settle()

    assert order == ["a1", "a2", "b1", "a3"]
    # The decisive fairness property: b1 (submitted last) was admitted before a3.
    assert order.index("b1") < order.index("a3")
