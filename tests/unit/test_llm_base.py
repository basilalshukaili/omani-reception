"""Unit tests for ``engine.llm.base``.

Covers the canonical value objects (``Message``, ``Pricing``, ``LLMDelta``),
the exception hierarchy, and the default ``LLMProvider.estimate_cost_usd``
arithmetic. The ABC is exercised through a tiny in-test concrete subclass so
we don't depend on any concrete adapter being importable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal

import pytest
from pydantic import ValidationError

from engine.core.types import LLMResponse, TokenUsage, ToolSchema
from engine.llm.base import (
    LLMDelta,
    LLMProvider,
    LLMProviderError,
    Message,
    MissingAPIKey,
    Pricing,
)

# ---------------------------------------------------------------------------
# Helper: a minimal concrete LLMProvider used only by tests in this module.
# ---------------------------------------------------------------------------


class _StubProvider(LLMProvider):
    """Concrete LLMProvider used to verify default ``estimate_cost_usd`` math."""

    name = "stub"

    def __init__(self, pricing_map: dict[str, Pricing]) -> None:
        self._pricing_map = pricing_map

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
        return LLMResponse(text="ok")

    async def stream(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
        model: str | None = None,
        temperature: float = 0.4,
        max_tokens: int = 800,
    ) -> AsyncIterator[LLMDelta]:
        if False:  # pragma: no cover — async generator protocol stub
            yield LLMDelta(text="")
        return

    def pricing(self, model: str) -> Pricing:
        return self._pricing_map[model]


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("role", ["system", "user", "assistant", "tool"])
def test_message_accepts_canonical_roles(role: str) -> None:
    msg = Message(role=role, content="hi")  # type: ignore[arg-type]
    assert msg.role == role
    assert msg.content == "hi"
    assert msg.tool_call_id is None
    assert msg.name is None


@pytest.mark.unit
def test_message_rejects_unknown_role() -> None:
    with pytest.raises(ValidationError):
        Message(role="moderator", content="x")  # type: ignore[arg-type]


@pytest.mark.unit
def test_message_forbids_extra_fields() -> None:
    """``extra="forbid"`` keeps the contract tight — typos must surface loudly."""
    with pytest.raises(ValidationError):
        Message(role="user", content="x", reasoning="hidden")  # type: ignore[call-arg]


@pytest.mark.unit
def test_message_carries_tool_metadata() -> None:
    msg = Message(role="tool", content="result", tool_call_id="t-1", name="lookup")
    assert msg.tool_call_id == "t-1"
    assert msg.name == "lookup"


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pricing_constructs_with_required_fields() -> None:
    p = Pricing(
        provider="gemini",
        model="gemini-2.5-flash",
        input_per_million_usd=0.075,
        output_per_million_usd=0.30,
    )
    assert p.provider == "gemini"
    assert p.cached_input_per_million_usd == 0.0  # default


@pytest.mark.unit
def test_pricing_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Pricing(  # type: ignore[call-arg]
            provider="x",
            model="y",
            input_per_million_usd=1.0,
            output_per_million_usd=1.0,
            spam="oops",
        )


# ---------------------------------------------------------------------------
# LLMDelta
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_llm_delta_defaults_are_empty() -> None:
    d = LLMDelta()
    assert d.text == ""
    assert d.finish_reason is None
    assert d.usage is None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_missing_api_key_is_provider_error() -> None:
    assert issubclass(MissingAPIKey, LLMProviderError)
    assert issubclass(LLMProviderError, Exception)


# ---------------------------------------------------------------------------
# LLMProvider.estimate_cost_usd
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_estimate_cost_usd_basic_math() -> None:
    """Hand-computed: 1M input @ $1, 0.5M output @ $2 -> $1.00 + $1.00 = $2.00."""
    pricing = Pricing(
        provider="stub",
        model="m",
        input_per_million_usd=1.0,
        output_per_million_usd=2.0,
    )
    provider = _StubProvider({"m": pricing})
    usage = TokenUsage(prompt_tokens=1_000_000, completion_tokens=500_000)

    cost = provider.estimate_cost_usd(usage, "m")

    assert cost == pytest.approx(2.0)


@pytest.mark.unit
def test_estimate_cost_usd_with_cache_discount() -> None:
    """Cached portion is billed at the cached rate; non-cached prompt at full rate."""
    pricing = Pricing(
        provider="stub",
        model="m",
        input_per_million_usd=10.0,
        cached_input_per_million_usd=1.0,
        output_per_million_usd=20.0,
    )
    provider = _StubProvider({"m": pricing})
    usage = TokenUsage(prompt_tokens=1_000_000, completion_tokens=100_000, cached_tokens=400_000)

    # 600k fresh prompt @ $10/M = $6.00
    # 400k cached prompt @ $1/M  = $0.40
    # 100k output @ $20/M        = $2.00
    cost = provider.estimate_cost_usd(usage, "m")

    assert cost == pytest.approx(6.0 + 0.4 + 2.0)


@pytest.mark.unit
def test_estimate_cost_usd_zero_tokens_is_zero() -> None:
    pricing = Pricing(
        provider="stub",
        model="m",
        input_per_million_usd=1.0,
        output_per_million_usd=1.0,
    )
    provider = _StubProvider({"m": pricing})
    cost = provider.estimate_cost_usd(TokenUsage(prompt_tokens=0, completion_tokens=0), "m")
    assert cost == 0.0


@pytest.mark.unit
def test_estimate_cost_usd_cached_exceeds_prompt_clamped_to_zero() -> None:
    """Guard against negative billed-prompt if cached_tokens > prompt_tokens (defensive)."""
    pricing = Pricing(
        provider="stub",
        model="m",
        input_per_million_usd=100.0,
        cached_input_per_million_usd=1.0,
        output_per_million_usd=0.0,
    )
    provider = _StubProvider({"m": pricing})
    # cached > prompt is nonsensical but should not yield a negative cost.
    usage = TokenUsage(prompt_tokens=100_000, completion_tokens=0, cached_tokens=500_000)

    cost = provider.estimate_cost_usd(usage, "m")

    # prompt_billed clamped to 0 -> only the 500k cached @ $1/M = $0.50
    assert cost == pytest.approx(0.5)


@pytest.mark.unit
def test_provider_is_abstract() -> None:
    """The ABC must refuse direct instantiation."""
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]
