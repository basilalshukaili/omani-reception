"""Anthropic Claude adapter — tested with mocked HTTP only (no live key needed).

Built on the official ``anthropic`` SDK's :class:`AsyncAnthropic` client. The
Messages API expects the system prompt as a top-level ``system`` parameter and
the conversation as alternating ``user`` / ``assistant`` blocks; tool results
come back as ``user`` messages with ``tool_result`` content blocks. The
adapter pulls the canonical :class:`Message` list apart accordingly.

Pricing is held in :data:`_PRICING` and is **approximate** — confirm against
the live pricing page before any real billing call. Cached prompt-tokens are
modelled as input savings via :class:`~engine.llm.base.Pricing`.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any, Literal

from engine.core.types import LLMResponse, TokenUsage, ToolSchema
from engine.llm.base import (
    LLMDelta,
    LLMProvider,
    LLMProviderError,
    Message,
    MissingAPIKey,
    Pricing,
)
from engine.llm.normalize import parse_anthropic_tool_calls, to_anthropic_tools
from engine.observability.logging import get_logger

logger = get_logger(__name__)


_PRICING: dict[str, Pricing] = {
    "claude-sonnet-4-6": Pricing(
        provider="claude",
        model="claude-sonnet-4-6",
        input_per_million_usd=3.0,
        cached_input_per_million_usd=0.30,
        output_per_million_usd=15.0,
    ),
    "claude-haiku-4-5": Pricing(
        provider="claude",
        model="claude-haiku-4-5",
        input_per_million_usd=1.0,
        cached_input_per_million_usd=0.10,
        output_per_million_usd=5.0,
    ),
}


class ClaudeProvider(LLMProvider):
    """Anthropic Claude adapter (mocked-tested, live capable when ANTHROPIC_API_KEY is set)."""

    name = "claude"

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = "claude-sonnet-4-6",
        *,
        require_api_key: bool = True,
    ) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "") or None
        if require_api_key and not self._api_key:
            raise MissingAPIKey(
                "ANTHROPIC_API_KEY not set — pass api_key=... or export ANTHROPIC_API_KEY."
            )
        self._default_model = default_model
        self._client: Any | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

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
        client = self._client_or_raise()
        model_id = model or self._default_model
        system_text, api_messages = _convert_messages(messages)
        if response_format == "json":
            # Anthropic has no native JSON mode; nudge via system instruction.
            json_hint = "Respond ONLY with valid JSON. No prose, no markdown fences."
            system_text = f"{system_text}\n\n{json_hint}".strip()

        kwargs: dict[str, Any] = {
            "model": model_id,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_text:
            kwargs["system"] = system_text
        if tools:
            kwargs["tools"] = to_anthropic_tools(tools)

        try:
            resp = await client.messages.create(**kwargs)
        except Exception as e:  # pragma: no cover
            raise LLMProviderError(f"Claude chat failed: {e}") from e
        return _to_llm_response(resp)

    async def stream(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
        model: str | None = None,
        temperature: float = 0.4,
        max_tokens: int = 800,
    ) -> AsyncIterator[LLMDelta]:
        client = self._client_or_raise()
        model_id = model or self._default_model
        system_text, api_messages = _convert_messages(messages)

        kwargs: dict[str, Any] = {
            "model": model_id,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_text:
            kwargs["system"] = system_text
        if tools:
            kwargs["tools"] = to_anthropic_tools(tools)

        try:
            stream_ctx = client.messages.stream(**kwargs)
        except Exception as e:  # pragma: no cover
            raise LLMProviderError(f"Claude stream failed: {e}") from e

        # The SDK's ``messages.stream`` is an async context manager that yields
        # individual text deltas via ``text_stream``. We surface each as an
        # :class:`LLMDelta` and emit a final delta with usage + stop_reason.
        async with stream_ctx as stream:
            async for text in stream.text_stream:
                yield LLMDelta(text=text)
            final = await stream.get_final_message()
            yield LLMDelta(
                text="",
                finish_reason=getattr(final, "stop_reason", None),
                usage=_extract_usage(final),
            )

    def pricing(self, model: str) -> Pricing:
        if model in _PRICING:
            return _PRICING[model]
        logger.warning("claude_pricing_fallback", requested_model=model)
        return _PRICING["claude-haiku-4-5"]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _client_or_raise(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise MissingAPIKey(
                "ANTHROPIC_API_KEY not set — adapter was constructed with"
                " require_api_key=False but no key was provided when chat()/stream() was invoked."
            )
        try:
            from anthropic import AsyncAnthropic
        except ImportError as e:  # pragma: no cover — dep is declared
            raise LLMProviderError(f"anthropic SDK not installed: {e}") from e
        self._client = AsyncAnthropic(api_key=self._api_key)
        return self._client


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def _convert_messages(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
    """Return ``(system_text, anthropic_messages)`` from canonical messages.

    Anthropic accepts ``user`` / ``assistant`` roles only; tool results are
    encoded as a ``user`` message whose ``content`` is a list with a
    ``tool_result`` block.
    """
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            if m.content:
                system_parts.append(m.content)
            continue
        if m.role == "tool":
            tool_use_id = m.tool_call_id or m.name or ""
            converted.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": m.content,
                        }
                    ],
                }
            )
            continue
        converted.append({"role": m.role, "content": m.content})
    return "\n".join(system_parts), converted


def _to_llm_response(resp: Any) -> LLMResponse:
    """Normalize an Anthropic ``Message`` response into our :class:`LLMResponse`."""
    text = _extract_text(resp)
    tool_calls = parse_anthropic_tool_calls(resp)
    usage = _extract_usage(resp)
    finish_reason = getattr(resp, "stop_reason", None)
    raw: dict[str, Any] | None = None
    model_dump = getattr(resp, "model_dump", None)
    if callable(model_dump):
        try:
            raw = model_dump()
        except Exception:  # pragma: no cover
            raw = None
    elif isinstance(resp, dict):
        raw = resp
    return LLMResponse(
        text=text,
        tool_calls=tool_calls,
        usage=usage,
        finish_reason=finish_reason,
        raw=raw,
    )


def _extract_text(resp: Any) -> str:
    content = getattr(resp, "content", None)
    if content is None and isinstance(resp, dict):
        content = resp.get("content")
    if not content:
        return ""
    pieces: list[str] = []
    for block in content:
        block_type = (
            getattr(block, "type", None) if not isinstance(block, dict) else block.get("type")
        )
        if block_type == "text":
            txt = block.get("text", "") if isinstance(block, dict) else getattr(block, "text", "")
            if txt:
                pieces.append(txt)
    return "".join(pieces)


def _extract_usage(resp: Any) -> TokenUsage | None:
    usage = getattr(resp, "usage", None)
    if usage is None and isinstance(resp, dict):
        usage = resp.get("usage")
    if usage is None:
        return None

    def _read(name: str) -> int:
        v = getattr(usage, name, None) if not isinstance(usage, dict) else usage.get(name)
        return int(v) if v is not None else 0

    cached = _read("cache_read_input_tokens")
    return TokenUsage(
        prompt_tokens=_read("input_tokens") + cached,
        completion_tokens=_read("output_tokens"),
        cached_tokens=cached,
    )


__all__ = ["ClaudeProvider"]
