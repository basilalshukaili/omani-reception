"""Provider-agnostic LLM interface.

Defines the abstract :class:`LLMProvider`, the canonical :class:`Message` and
:class:`Pricing` value objects, the streaming :class:`LLMDelta`, and the
exceptions raised by adapters (:class:`LLMProviderError`,
:class:`MissingAPIKey`).

Concrete adapters live in :mod:`engine.llm.gemini`, :mod:`engine.llm.claude`,
and :mod:`engine.llm.openai`. They MUST translate any provider-specific failure
into :class:`LLMProviderError` (or a subclass) so callers can handle errors
uniformly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Literal

from pydantic import BaseModel, ConfigDict

from engine.core.types import LLMResponse, TokenUsage, ToolSchema


class Message(BaseModel):
    """One message in an LLM conversation.

    The four canonical roles map to provider-native equivalents inside each
    adapter. ``tool_call_id`` and ``name`` are set when ``role == "tool"`` and
    the message represents a tool-result being fed back to the model.
    """

    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None
    name: str | None = None


class Pricing(BaseModel):
    """Per-1M-token USD prices used by the cost tracker (P6)."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    input_per_million_usd: float
    cached_input_per_million_usd: float = 0.0
    output_per_million_usd: float


class LLMDelta(BaseModel):
    """One incremental delta yielded by :meth:`LLMProvider.stream`."""

    model_config = ConfigDict(extra="forbid")

    text: str = ""
    finish_reason: str | None = None
    usage: TokenUsage | None = None


class LLMProviderError(Exception):
    """Raised when a provider call fails non-recoverably.

    Adapters wrap their SDK exceptions in this (or a subclass) so callers can
    catch a single type regardless of the underlying provider.
    """


class MissingAPIKey(LLMProviderError):
    """Raised when an adapter is invoked without its API key set in env."""


class LLMProvider(ABC):
    """Provider-agnostic LLM interface.

    Subclasses set ``name`` to a short provider identifier (``"gemini"``,
    ``"claude"``, ``"openai"``) and implement :meth:`chat`, :meth:`stream`, and
    :meth:`pricing`. Cost estimation is provided here via
    :meth:`estimate_cost_usd` and uses :meth:`pricing` lookups.
    """

    name: str = ""

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
        model: str | None = None,
        temperature: float = 0.4,
        max_tokens: int = 800,
        response_format: Literal["text", "json"] = "text",
    ) -> LLMResponse:
        """Send a non-streaming chat request and return a normalized response."""

    @abstractmethod
    def stream(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
        model: str | None = None,
        temperature: float = 0.4,
        max_tokens: int = 800,
    ) -> AsyncIterator[LLMDelta]:
        """Yield streaming deltas for a chat request.

        Implementations are async generators — the return type is
        ``AsyncIterator[LLMDelta]`` rather than ``Awaitable[...]`` so callers
        can ``async for delta in provider.stream(...)`` without an extra await.
        """

    @abstractmethod
    def pricing(self, model: str) -> Pricing:
        """Return the :class:`Pricing` row for ``model`` (raises ``KeyError`` if unknown)."""

    def estimate_cost_usd(self, usage: TokenUsage, model: str) -> float:
        """Estimate USD cost of a single call from token counts and model id."""
        p = self.pricing(model)
        prompt_billed = max(usage.prompt_tokens - usage.cached_tokens, 0)
        return (
            prompt_billed / 1_000_000 * p.input_per_million_usd
            + usage.cached_tokens / 1_000_000 * p.cached_input_per_million_usd
            + usage.completion_tokens / 1_000_000 * p.output_per_million_usd
        )


__all__ = [
    "LLMDelta",
    "LLMProvider",
    "LLMProviderError",
    "Message",
    "MissingAPIKey",
    "Pricing",
]
