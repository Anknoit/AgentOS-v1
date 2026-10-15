"""LLM provider abstraction for the Phase 0 agent-loop spike.

Two implementations behind one ``LLMProvider`` protocol:

* ``MockProvider`` (default) — deterministic, no network, no key. Streams a canned reply token
  by token and reports token counts, so the whole spike (loop -> stream -> usage_event) runs
  offline and in CI.
* ``OpenAIProvider`` — real streaming completion with usage captured from the final chunk.

The spike proves exactly the hard unknown the plan calls out: capture token usage from a
provider response and write **one** ``usage_event``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from app.config.settings import Settings


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class StreamChunk:
    delta: str = ""
    done: bool = False
    usage: Usage | None = None


class LLMProvider(Protocol):
    name: str

    def stream(self, prompt: str, *, model: str) -> AsyncIterator[StreamChunk]: ...


def _count_tokens(text: str) -> int:
    """Crude but deterministic token estimate (~¾ of word count + punctuation)."""
    return max(1, len(text.split()))


class MockProvider:
    name = "mock"

    async def stream(self, prompt: str, *, model: str) -> AsyncIterator[StreamChunk]:
        reply = (
            f"Hello from the AgentOS mock agent. You said: '{prompt.strip()}'. "
            "This response is deterministic so Phase 0 can run with no API key."
        )
        words = reply.split(" ")
        for i, w in enumerate(words):
            yield StreamChunk(delta=w + (" " if i < len(words) - 1 else ""))
        yield StreamChunk(
            done=True,
            usage=Usage(input_tokens=_count_tokens(prompt), output_tokens=_count_tokens(reply)),
        )


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)

    async def stream(self, prompt: str, *, model: str) -> AsyncIterator[StreamChunk]:
        stream = await self._client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in stream:
            if chunk.usage is not None:
                yield StreamChunk(
                    done=True,
                    usage=Usage(
                        input_tokens=chunk.usage.prompt_tokens,
                        output_tokens=chunk.usage.completion_tokens,
                    ),
                )
                continue
            if chunk.choices and chunk.choices[0].delta.content:
                yield StreamChunk(delta=chunk.choices[0].delta.content)


def get_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("AGENTOS_LLM_PROVIDER=openai but OPENAI_API_KEY is not set")
        return OpenAIProvider(settings.openai_api_key)
    return MockProvider()
