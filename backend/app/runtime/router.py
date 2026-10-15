"""Multi-provider model routing + failover (Phase 5, build task 3).

A fleet should not go dark because one provider degrades, and it should prefer the cheapest model
that can do the job. :class:`ModelRouter` sits behind the same ``LLMProvider.stream`` contract the
kernel already uses and adds two things over a single provider:

* **cost-aware selection** — candidates (``provider:model`` pairs) are ordered cheapest-first using
  list prices, among providers whose circuit is healthy;
* **failover** — if the chosen provider errors *at request time* (the dominant failure mode:
  unreachable, auth, rate-limit), the router moves to the next candidate. Once the first token has
  streamed, the router is committed to that provider (a response can't be re-opened mid-stream), so
  the kernel attributes the usage event to whoever actually served it (``last_provider`` /
  ``last_model``) — metering stays exactly-once and correctly attributed through a failover.

A :class:`ProviderHealth` circuit breaker trips a provider after N consecutive failures and keeps
it deprioritised for a cooldown, so the router stops hammering a known-down provider but still falls
back to it if nothing healthier exists. This is the in-process contract; a managed gateway would
implement the same ordering/health logic server-side.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from decimal import Decimal

from app.config.settings import Settings
from app.core.logging import get_logger
from app.runtime.providers import LLMProvider, StreamChunk, make_provider

log = get_logger(__name__)


@dataclass(frozen=True)
class Candidate:
    provider: str
    model: str

    @classmethod
    def parse(cls, spec: str) -> Candidate:
        provider, _, model = spec.partition(":")
        return cls(provider=provider.strip(), model=(model.strip() or provider.strip()))


class ProviderHealth:
    """Per-provider circuit breaker: opens after ``threshold`` consecutive failures."""

    def __init__(self, *, threshold: int = 3, cooldown_s: float = 30.0) -> None:
        self._threshold = max(1, threshold)
        self._cooldown = cooldown_s
        self._failures: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}

    def record_success(self, provider: str) -> None:
        self._failures[provider] = 0
        self._opened_at.pop(provider, None)

    def record_failure(self, provider: str) -> None:
        n = self._failures.get(provider, 0) + 1
        self._failures[provider] = n
        if n >= self._threshold:
            self._opened_at[provider] = time.monotonic()

    def is_open(self, provider: str, *, now: float | None = None) -> bool:
        opened = self._opened_at.get(provider)
        if opened is None:
            return False
        now = now if now is not None else time.monotonic()
        if now - opened >= self._cooldown:  # cooldown elapsed: half-open, let it be tried again
            return False
        return True

    def snapshot(self) -> dict[str, dict]:
        return {
            p: {
                "consecutive_failures": self._failures.get(p, 0),
                "circuit_open": self.is_open(p),
            }
            for p in set(self._failures) | set(self._opened_at)
        }


# List prices (USD per 1M tokens) used only for cost-aware *ordering*; the ledger prices against
# the tenant's real rate card. Kept in sync with services.ratecards.DEFAULT_MODEL_PRICES.
def _default_price_map() -> dict[str, dict[str, str]]:
    from app.services.ratecards import DEFAULT_MODEL_PRICES

    return DEFAULT_MODEL_PRICES


@dataclass
class ModelRouter:
    providers: dict[str, LLMProvider]
    candidates: list[Candidate]
    health: ProviderHealth = field(default_factory=ProviderHealth)
    price_map: dict[str, dict[str, str]] = field(default_factory=_default_price_map)
    last_provider: str | None = None
    last_model: str | None = None

    def _cost_rank(self, cand: Candidate) -> Decimal:
        prices = self.price_map.get(cand.model) or self.price_map.get("__default__", {})
        return Decimal(prices.get("input", "0")) + Decimal(prices.get("output", "0"))

    def _sort_key(self, c: Candidate) -> tuple:
        # Healthy first, then cheapest; provider/model break ties for a deterministic order.
        return (self.health.is_open(c.provider), self._cost_rank(c), c.provider, c.model)

    def _ordered(self) -> list[Candidate]:
        return sorted(self.candidates, key=self._sort_key)

    async def stream(self, prompt: str, *, model: str | None = None) -> AsyncIterator[StreamChunk]:
        self.last_provider = None
        self.last_model = None
        last_exc: Exception | None = None
        for cand in self._ordered():
            provider = self.providers.get(cand.provider)
            if provider is None:
                continue
            try:
                agen = provider.stream(prompt, model=cand.model)
                first = await agen.__anext__()
            except StopAsyncIteration:  # empty but successful stream
                self.health.record_success(cand.provider)
                self.last_provider, self.last_model = cand.provider, cand.model
                return
            except Exception as exc:  # request-time failure: fail over to the next candidate
                last_exc = exc
                self.health.record_failure(cand.provider)
                log.warning(
                    "router.failover", provider=cand.provider, model=cand.model, error=str(exc)
                )
                continue
            # Committed to this provider — stream it through and attribute usage to it.
            self.health.record_success(cand.provider)
            self.last_provider, self.last_model = cand.provider, cand.model
            yield first
            async for chunk in agen:
                yield chunk
            return
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("model router: no candidate provider available")


class SingleProviderRouter:
    """The no-failover path: one provider, no health/cost logic (default behaviour, back-compat)."""

    def __init__(self, provider: LLMProvider, model: str) -> None:
        self._provider = provider
        self.last_provider = provider.name
        self.last_model = model

    async def stream(self, prompt: str, *, model: str | None = None) -> AsyncIterator[StreamChunk]:
        used = model or self.last_model
        self.last_model = used
        async for chunk in self._provider.stream(prompt, model=used):
            yield chunk


# Process-wide circuit state, shared across runs so a provider that trips stays deprioritised for
# the whole process (and the ops endpoint can report it), not just within one run.
_health: ProviderHealth | None = None


def get_health(settings: Settings | None = None) -> ProviderHealth:
    global _health
    if _health is None:
        if settings is None:
            from app.config.settings import get_settings

            settings = get_settings()
        _health = ProviderHealth(
            threshold=settings.provider_circuit_threshold,
            cooldown_s=settings.provider_circuit_cooldown_s,
        )
    return _health


def set_health(health: ProviderHealth | None) -> None:
    global _health
    _health = health


def build_router(settings: Settings):
    """Build the router for a run: ``ModelRouter`` when failover is on, else a single provider."""
    if not settings.provider_failover or not settings.provider_candidates:
        from app.runtime.providers import get_provider

        return SingleProviderRouter(get_provider(settings), settings.llm_model)

    candidates = [Candidate.parse(spec) for spec in settings.provider_candidates]
    providers: dict[str, LLMProvider] = {}
    for cand in candidates:
        if cand.provider not in providers:
            providers[cand.provider] = make_provider(cand.provider, settings)
    return ModelRouter(
        providers=providers, candidates=candidates, health=get_health(settings)
    )
