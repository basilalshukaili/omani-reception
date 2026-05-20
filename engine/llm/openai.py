"""OpenAI adapter — tested with mocked HTTP only (no live key needed).

Built on the official ``openai`` SDK's :class:`AsyncOpenAI` client and the
``chat.completions`` endpoint. The system prompt stays inline in the messages
list (OpenAI accepts a leading ``{"role": "system", ...}`` entry). Tool calls
come back as ``message.tool_calls`` with JSON-string arguments, which the
shared normaliser parses into a canonical :class:`ToolCall`.

OpenAI's JSON mode is enabled via ``response_format={"type": "json_object"}``
when ``response_format == "json"``. Pricing is approximate; update with care.
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
from engine.llm.normalize import parse_openai_tool_calls, to_openai_tools
from engine.observability.logging import get_logger

logger = get_logger(__name__)


_PRICING: dict[str, Pricing] = {
    "gpt-4o": Pricing(
        provider="openai",
        model="gpt-4o",
        input_per_million_usd=2.50,
        cached_input_per_million_usd=1.25,
        output_per_million_usd=10.0,
    ),
    "gpt-4o-mini": Pricing(
        provider="openai",
        model="gpt-4o-mini",
        input_per_million_usd=0.15,
        cached_input_per_million_usd=0.075,
        output_per_million_usd=0.60,
    ),
}


class OpenAIProvider(LLMProvider):
    """OpenAI adapter (mocked-tested, live capable when OPENAI_API_KEY is set)."""

    name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = "gpt-4o-mini",
        *,
        require_api_key: bool = True,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "") or None
        if require_api_key and not self._api_key:
            raise MissingAPIKey(
                "OPENAI_API_KEY not set — pass api_key=... or export OPENAI_API_KEY."
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
        api_messages = _convert_messages(messages)
        kwargs: dict[str, Any] = {
            "model": model_id,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = to_openai_tools(tools)
        if response_format == "json":
            kwargs["response_format"] = {"type": "json_object"}

        try:
            resp = await client.chat.completions.create(**kwargs)
        except Exception as e:  # pragma: no cover
            raise LLMProviderError(f"OpenAI chat failed: {e}") from e
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
        api_messages = _convert_messages(messages)
        kwargs: dict[str, Any] = {
            "model": model_id,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = to_openai_tools(tools)

        try:
            stream = await client.chat.completions.create(**kwargs)
        except Exception as e:  # pragma: no cover
            raise LLMProviderError(f"OpenAI stream failed: {e}") from e

        async for chunk in stream:
            text_piece = ""
            finish_reason: str | None = None
            choices = getattr(chunk, "choices", None) or []
            if choices:
                delta = getattr(choices[0], "delta", None)
                if delta is not None:
                    content = getattr(delta, "content", None)
                    if content:
                        text_piece = content
                finish_reason = getattr(choices[0], "finish_reason", None)
            usage = _extract_usage(chunk)
            yield LLMDelta(text=text_piece, finish_reason=finish_reason, usage=usage)

    def pricing(self, model: str) -> Pricing:
        if model in _PRICING:
            return _PRICING[model]
        logger.warning("openai_pricing_fallback", requested_model=model)
        return _PRICING["gpt-4o-mini"]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _client_or_raise(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise MissingAPIKey(
                "OPENAI_API_KEY not set — adapter was constructed with"
                " require_api_key=False but no key was provided when chat()/stream() was invoked."
            )
        try:
            from openai import AsyncOpenAI
        except ImportError as e:  # pragma: no cover
            raise LLMProviderError(f"openai SDK not installed: {e}") from e
        self._client = AsyncOpenAI(api_key=self._api_key)
        return self._client


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def _convert_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert canonical :class:`Message`s into OpenAI chat-completion shape."""
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": m.tool_call_id or "",
                    "content": m.content,
                }
            )
            continue
        entry: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.role == "assistant" and m.name:
            entry["name"] = m.name
        out.append(entry)
    return out


def _to_llm_response(resp: Any) -> LLMResponse:
    """Normalize a :class:`ChatCompletion` into our :class:`LLMResponse`."""
    text = _extract_text(resp)
    tool_calls = parse_openai_tool_calls(resp)
    usage = _extract_usage(resp)
    finish_reason = _extract_finish_reason(resp)
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
    choices = getattr(resp, "choices", None)
    if choices is None and isinstance(resp, dict):
        choices = resp.get("choices")
    if not choices:
        return ""
    first = choices[0]
    message = getattr(first, "message", None)
    if message is None and isinstance(first, dict):
        message = first.get("message")
    if message is None:
        return ""
    content = (
        message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
    )
    return content or ""


def _extract_finish_reason(resp: Any) -> str | None:
    choices = getattr(resp, "choices", None)
    if choices is None and isinstance(resp, dict):
        choices = resp.get("choices")
    if not choices:
        return None
    first = choices[0]
    reason = getattr(first, "finish_reason", None)
    if reason is None and isinstance(first, dict):
        reason = first.get("finish_reason")
    return reason


def _extract_usage(resp: Any) -> TokenUsage | None:
    usage = getattr(resp, "usage", None)
    if usage is None and isinstance(resp, dict):
        usage = resp.get("usage")
    if usage is None:
        return None

    def _read(name: str) -> int:
        v = getattr(usage, name, None) if not isinstance(usage, dict) else usage.get(name)
        return int(v) if v is not None else 0

    cached = 0
    details = getattr(usage, "prompt_tokens_details", None)
    if details is None and isinstance(usage, dict):
        details = usage.get("prompt_tokens_details")
    if details is not None:
        c = (
            details.get("cached_tokens")
            if isinstance(details, dict)
            else getattr(details, "cached_tokens", None)
        )
        if c is not None:
            cached = int(c)

    prompt = _read("prompt_tokens")
    completion = _read("completion_tokens")
    if prompt == 0 and completion == 0 and cached == 0:
        return None
    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        cached_tokens=cached,
    )


__all__ = ["OpenAIProvider"]
