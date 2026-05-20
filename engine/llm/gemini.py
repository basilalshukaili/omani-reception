"""Google Gemini adapter — the only live LLM provider for v1.

Uses the **new** ``google-genai`` SDK (``from google import genai``). The
adapter exposes the provider-agnostic interface defined in
:mod:`engine.llm.base`, translating canonical :class:`Message` /
:class:`ToolSchema` objects into Gemini's ``Content`` / ``FunctionDeclaration``
shapes and back.

Default models: ``gemini-2.5-flash`` for turns, ``gemini-2.5-pro`` for the
dialect evaluation pass (P4). Pricing is held in :data:`_PRICING` and consumed
by :meth:`GeminiProvider.pricing`. **No live call happens at import time** —
the SDK client is constructed lazily and only the API key is touched in
``__init__``.
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
from engine.llm.normalize import parse_gemini_tool_calls, to_gemini_tools
from engine.observability.logging import get_logger

logger = get_logger(__name__)


# Per-1M-token USD pricing. Source: Google Gemini pricing pages (late 2024 /
# early 2025). Update via ADR when prices change. Unknown models fall back to
# Flash pricing (the cheapest tier) — over-reporting cost is safer than under.
_PRICING: dict[str, Pricing] = {
    "gemini-2.5-flash": Pricing(
        provider="gemini",
        model="gemini-2.5-flash",
        input_per_million_usd=0.075,
        cached_input_per_million_usd=0.01875,
        output_per_million_usd=0.30,
    ),
    "gemini-2.5-pro": Pricing(
        provider="gemini",
        model="gemini-2.5-pro",
        input_per_million_usd=1.25,
        cached_input_per_million_usd=0.3125,
        output_per_million_usd=5.00,
    ),
    "gemini-2.0-flash": Pricing(
        provider="gemini",
        model="gemini-2.0-flash",
        input_per_million_usd=0.10,
        cached_input_per_million_usd=0.025,
        output_per_million_usd=0.40,
    ),
}


class GeminiProvider(LLMProvider):
    """Live Gemini adapter built on the ``google-genai`` SDK.

    The client is built lazily inside :meth:`_client_or_raise` so that
    constructing the adapter with ``require_api_key=False`` (as the factory
    does in tests) never fails — only the first live call does. The Gemini
    SDK uses ``client.aio.models.generate_content(...)`` for async access.
    """

    name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = "gemini-2.5-flash",
        *,
        require_api_key: bool = True,
    ) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "") or None
        if require_api_key and not self._api_key:
            raise MissingAPIKey(
                "GEMINI_API_KEY not set — pass api_key=... or export GEMINI_API_KEY."
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
        contents, system_text = _convert_messages(messages)
        config = _build_config(
            system_text=system_text,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            tools=tools,
        )
        try:
            resp = await client.aio.models.generate_content(
                model=model_id,
                contents=contents,
                config=config,
            )
        except Exception as e:  # pragma: no cover — exercised via mocked test
            raise LLMProviderError(f"Gemini chat failed: {e}") from e
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
        contents, system_text = _convert_messages(messages)
        config = _build_config(
            system_text=system_text,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format="text",
            tools=tools,
        )
        try:
            stream = await client.aio.models.generate_content_stream(
                model=model_id,
                contents=contents,
                config=config,
            )
        except Exception as e:  # pragma: no cover
            raise LLMProviderError(f"Gemini stream failed: {e}") from e

        async for chunk in stream:
            text = getattr(chunk, "text", None) or ""
            usage = _extract_usage(chunk)
            finish_reason = _extract_finish_reason(chunk)
            yield LLMDelta(text=text, finish_reason=finish_reason, usage=usage)

    def pricing(self, model: str) -> Pricing:
        if model in _PRICING:
            return _PRICING[model]
        # Fallback to Flash pricing for unknown variants; log a warning so a
        # human can add it to the table.
        logger.warning("gemini_pricing_fallback", requested_model=model)
        return _PRICING["gemini-2.5-flash"]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _client_or_raise(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise MissingAPIKey(
                "GEMINI_API_KEY not set — adapter constructed with require_api_key=False"
                " but no key was provided when chat()/stream() was invoked."
            )
        try:
            from google import genai
        except ImportError as e:  # pragma: no cover — dep is declared
            raise LLMProviderError(f"google-genai SDK not installed: {e}") from e
        self._client = genai.Client(api_key=self._api_key)
        return self._client


# ---------------------------------------------------------------------------
# Message + config conversion helpers (kept module-level so tests can call them)
# ---------------------------------------------------------------------------


def _convert_messages(messages: list[Message]) -> tuple[list[dict[str, Any]], str]:
    """Split canonical messages into Gemini ``contents`` + system instruction.

    Returns a ``(contents, system_text)`` pair. ``contents`` uses dict-shaped
    parts (``{"role": ..., "parts": [...]}``) which the SDK accepts directly
    via its ``ContentDict`` typed-dict union — keeping the code SDK-version
    tolerant. The role mapping is ``assistant -> model``; ``tool`` messages
    become ``function_response`` parts under a ``user`` role.
    """
    contents: list[dict[str, Any]] = []
    system_parts: list[str] = []
    for m in messages:
        if m.role == "system":
            if m.content:
                system_parts.append(m.content)
            continue
        if m.role == "tool":
            # Tool results go back to Gemini as a function_response part. The
            # ``name`` is required; fall back to ``tool_call_id`` if missing.
            name = m.name or m.tool_call_id or "tool"
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "function_response": {
                                "name": name,
                                "response": {"result": m.content},
                            }
                        }
                    ],
                }
            )
            continue
        role = "model" if m.role == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m.content}]})
    return contents, "\n".join(system_parts)


def _build_config(
    *,
    system_text: str,
    temperature: float,
    max_tokens: int,
    response_format: Literal["text", "json"],
    tools: list[ToolSchema] | None,
) -> Any:
    """Build a :class:`google.genai.types.GenerateContentConfig` for one call.

    Lazy-imports the SDK types module so unit tests that mock the client never
    need the dependency available at import time of *this* module's tests.
    """
    from google.genai import types as gtypes

    kwargs: dict[str, Any] = {
        "temperature": temperature,
        "max_output_tokens": max_tokens,
    }
    if system_text:
        kwargs["system_instruction"] = system_text
    if response_format == "json":
        kwargs["response_mime_type"] = "application/json"
    if tools:
        kwargs["tools"] = to_gemini_tools(tools)
    return gtypes.GenerateContentConfig(**kwargs)


def _to_llm_response(resp: Any) -> LLMResponse:
    """Normalize a Gemini ``GenerateContentResponse`` into our :class:`LLMResponse`."""
    text = getattr(resp, "text", None) or ""
    tool_calls = parse_gemini_tool_calls(resp)
    usage = _extract_usage(resp)
    finish_reason = _extract_finish_reason(resp)
    raw: dict[str, Any] | None = None
    to_json = getattr(resp, "to_json_dict", None)
    if callable(to_json):
        try:
            raw = to_json()
        except Exception:  # pragma: no cover — defensive
            raw = None
    return LLMResponse(
        text=text,
        tool_calls=tool_calls,
        usage=usage,
        finish_reason=finish_reason,
        raw=raw,
    )


def _extract_usage(resp: Any) -> TokenUsage | None:
    usage_meta = getattr(resp, "usage_metadata", None)
    if usage_meta is None:
        return None
    prompt = getattr(usage_meta, "prompt_token_count", None) or 0
    completion = getattr(usage_meta, "candidates_token_count", None) or 0
    cached = getattr(usage_meta, "cached_content_token_count", None) or 0
    if prompt == 0 and completion == 0 and cached == 0:
        return None
    return TokenUsage(
        prompt_tokens=int(prompt),
        completion_tokens=int(completion),
        cached_tokens=int(cached),
    )


def _extract_finish_reason(resp: Any) -> str | None:
    candidates = getattr(resp, "candidates", None) or []
    if not candidates:
        return None
    reason = getattr(candidates[0], "finish_reason", None)
    if reason is None:
        return None
    # finish_reason may be an enum — coerce to a plain string.
    return getattr(reason, "name", None) or str(reason)


__all__ = ["GeminiProvider"]
