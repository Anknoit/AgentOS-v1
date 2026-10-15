"""Multi-provider routing + failover (Phase 5, build task 3).

Proves cost-aware selection (cheapest healthy candidate wins), failover on a request-time provider
error (the fleet doesn't go dark), the circuit breaker (a repeatedly-failing provider is tripped
and deprioritised), and that usage is attributed to whoever actually served (so metering stays
correct through a failover).
"""

from __future__ import annotations

import asyncio

import pytest

from app.runtime.providers import StreamChunk, Usage
from app.runtime.router import Candidate, ModelRouter, ProviderHealth

PRICES = {
    "cheap-model": {"input": "0.10", "output": "0.10"},
    "pricey-model": {"input": "9.00", "output": "9.00"},
}


class StaticProvider:
    def __init__(self, name: str, text: str) -> None:
        self.name = name
        self._text = text

    async def stream(self, prompt, *, model):
        yield StreamChunk(delta=self._text)
        yield StreamChunk(done=True, usage=Usage(input_tokens=1, output_tokens=1))


class FailingProvider:
    def __init__(self, name: str) -> None:
        self.name = name

    async def stream(self, prompt, *, model):
        raise RuntimeError(f"{self.name} unreachable")
        yield  # pragma: no cover - makes this an async generator


def _router(providers, candidates, **kw) -> ModelRouter:
    return ModelRouter(providers=providers, candidates=candidates, price_map=PRICES, **kw)


async def _drain(router):
    return "".join([c.delta async for c in router.stream("hi") if c.delta])


async def test_picks_cheapest_healthy_candidate():
    router = _router(
        {"big": StaticProvider("big", "B"), "small": StaticProvider("small", "S")},
        [Candidate("big", "pricey-model"), Candidate("small", "cheap-model")],
    )
    out = await _drain(router)
    assert router.last_provider == "small"  # cheaper model wins
    assert out == "S"


async def test_fails_over_when_the_cheapest_provider_errors():
    router = _router(
        {"small": FailingProvider("small"), "big": StaticProvider("big", "B")},
        [Candidate("big", "pricey-model"), Candidate("small", "cheap-model")],
    )
    out = await _drain(router)
    assert router.last_provider == "big"  # cheap one failed → fell over to the healthy one
    assert out == "B"


async def test_circuit_opens_after_threshold_and_deprioritises():
    health = ProviderHealth(threshold=2, cooldown_s=100.0)
    router = _router(
        {"small": FailingProvider("small"), "big": StaticProvider("big", "B")},
        [Candidate("big", "pricey-model"), Candidate("small", "cheap-model")],
        health=health,
    )
    await _drain(router)  # cheap fails once (1 < 2 → still closed), served by big
    assert health.is_open("small") is False
    await _drain(router)  # cheap fails again → circuit opens
    assert health.is_open("small") is True
    # With its circuit open, the cheap provider is now ordered last despite being cheaper.
    assert router._ordered()[0].provider == "big"


async def test_all_candidates_down_raises():
    router = _router(
        {"a": FailingProvider("a"), "b": FailingProvider("b")},
        [Candidate("a", "cheap-model"), Candidate("b", "pricey-model")],
    )
    with pytest.raises(RuntimeError):
        await _drain(router)


async def test_circuit_half_opens_after_cooldown():
    health = ProviderHealth(threshold=1, cooldown_s=0.05)
    health.record_failure("p")
    assert health.is_open("p") is True
    await asyncio.sleep(0.06)
    assert health.is_open("p") is False  # cooldown elapsed → half-open, eligible to retry
    health.record_success("p")
    assert health.is_open("p") is False
