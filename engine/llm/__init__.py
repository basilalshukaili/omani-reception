"""Provider-agnostic LLM adapter layer.

Public surface:

* :class:`~engine.llm.base.LLMProvider` — abstract base
* :class:`~engine.llm.base.Message`, :class:`~engine.llm.base.Pricing`,
  :class:`~engine.llm.base.LLMDelta` — value objects
* :class:`~engine.llm.base.LLMProviderError`,
  :class:`~engine.llm.base.MissingAPIKey` — exceptions
* :func:`~engine.llm.factory.make_llm_provider` — config-driven factory

Concrete adapters (``GeminiProvider``, ``ClaudeProvider``, ``OpenAIProvider``)
are imported lazily by the factory so importing :mod:`engine.llm` does not
pull every SDK at startup.
"""

from __future__ import annotations

from engine.llm.base import (
    LLMDelta,
    LLMProvider,
    LLMProviderError,
    Message,
    MissingAPIKey,
    Pricing,
)
from engine.llm.factory import make_llm_provider

__all__ = [
    "LLMDelta",
    "LLMProvider",
    "LLMProviderError",
    "Message",
    "MissingAPIKey",
    "Pricing",
    "make_llm_provider",
]
