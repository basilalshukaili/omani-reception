"""Provider selection — pick a concrete :class:`LLMProvider` from config or env.

The orchestrator does not import individual adapters; it always goes through
:func:`make_llm_provider`. ``LLM_PROVIDER`` env var overrides any caller-passed
default — convenient for the ``--llm-provider`` CLI flag and for A/B testing
without editing config.
"""

from __future__ import annotations

import os

from engine.llm.base import LLMProvider


def make_llm_provider(
    provider: str | None = None,
    model: str | None = None,
    *,
    require_api_key: bool = True,
) -> LLMProvider:
    """Construct an LLM adapter.

    Args:
        provider: One of ``"gemini"``, ``"claude"``, ``"openai"``. If ``None``,
            falls back to the ``LLM_PROVIDER`` env var, then to ``"gemini"``.
        model: Optional default model name for the chosen provider. ``None``
            falls back to the per-provider default.
        require_api_key: When ``False``, the adapter is constructed without
            verifying the API key — the first ``chat``/``stream`` call will
            raise :class:`engine.llm.base.MissingAPIKey` instead. Used by
            tests that mock the SDK client.
    """
    chosen = (provider or os.environ.get("LLM_PROVIDER") or "gemini").strip().lower()
    if chosen == "gemini":
        from engine.llm.gemini import GeminiProvider

        return GeminiProvider(
            default_model=model or "gemini-2.5-flash",
            require_api_key=require_api_key,
        )
    if chosen == "claude":
        from engine.llm.claude import ClaudeProvider

        return ClaudeProvider(
            default_model=model or "claude-sonnet-4-6",
            require_api_key=require_api_key,
        )
    if chosen == "openai":
        from engine.llm.openai import OpenAIProvider

        return OpenAIProvider(
            default_model=model or "gpt-4o-mini",
            require_api_key=require_api_key,
        )
    raise ValueError(f"Unknown LLM provider: {chosen!r} (expected 'gemini' | 'claude' | 'openai')")


__all__ = ["make_llm_provider"]
