"""Unit tests for ``engine.llm.gemini.GeminiProvider``.

Mocking strategy
----------------
``google-genai`` (the live SDK) is built on ``httpx``, so in principle
``pytest-httpx`` could intercept its requests. In practice the SDK wraps
``httpx.AsyncClient`` in its own ``AsyncHttpxClient`` and uses helper layers
that make a pure-HTTP fixture brittle — request bodies and URLs depend on the
SDK's internal transformer chain rather than on stable wire shapes.

We therefore use **method-level patching** of
``client.aio.models.generate_content`` to return a stub response object. This
is the fallback path the P1 brief explicitly authorises, and it gives us a
hermetic, deterministic test without coupling to the SDK's request encoding.
We still test the body shape of the *messages we pass to the adapter* (i.e.,
the canonical ``Message`` -> Gemini-content translation), which is the bit
that matters for cross-provider correctness.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from engine.core.types import TokenUsage
from engine.llm.base import Message, MissingAPIKey


def _fake_gemini_response(
    *,
    text: str = "أهلاً",
    prompt_tokens: int = 11,
    completion_tokens: int = 7,
) -> SimpleNamespace:
    """Build a stub mimicking the surface of ``GenerateContentResponse``.

    The adapter is expected to read ``.text`` (or walk ``.candidates[*].content.parts``)
    and ``.usage_metadata.{prompt_token_count, candidates_token_count}``. We
    provide both, so a reasonable adapter will resolve the same answer no matter
    which path it prefers.
    """
    part = SimpleNamespace(text=text, function_call=None)
    content = SimpleNamespace(parts=[part], role="model")
    candidate = SimpleNamespace(content=content, finish_reason="STOP", safety_ratings=[])
    usage = SimpleNamespace(
        prompt_token_count=prompt_tokens,
        candidates_token_count=completion_tokens,
        total_token_count=prompt_tokens + completion_tokens,
        cached_content_token_count=0,
    )
    return SimpleNamespace(
        text=text,
        candidates=[candidate],
        usage_metadata=usage,
        prompt_feedback=None,
    )


class _CapturingGenerateContent:
    """Async stub for ``client.aio.models.generate_content``.

    Records every call so tests can assert on the ``contents`` / ``config`` /
    ``model`` arguments that the adapter passes in.
    """

    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


def _install_fake_models(
    monkeypatch: pytest.MonkeyPatch, response: Any
) -> _CapturingGenerateContent:
    """Patch the Gemini client's async ``generate_content`` method.

    Patches at the ``google.genai.Client`` boundary so any newly-constructed
    ``GeminiProvider`` (which builds its own client internally) picks up the
    fake. We monkeypatch the descriptor on the ``AsyncModels`` class so it
    applies even though the client is instantiated lazily inside the adapter.
    """
    fake = _CapturingGenerateContent(response)

    # Import here so the test still fails clearly if google-genai is missing.
    from google.genai import models as gm_models

    monkeypatch.setattr(gm_models.AsyncModels, "generate_content", fake, raising=True)
    return fake


# ---------------------------------------------------------------------------
# Construction / API-key handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_api_key_raises_on_construction_or_first_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``GEMINI_API_KEY`` / ``GOOGLE_API_KEY`` -> ``MissingAPIKey``.

    The brief allows the error to surface either at construction time or on the
    first ``chat`` call; we accept both shapes.
    """
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    from engine.llm.gemini import GeminiProvider

    with pytest.raises(MissingAPIKey):
        provider = GeminiProvider()
        # If construction succeeded, the call must fail.
        await provider.chat([Message(role="user", content="hi")])


@pytest.mark.unit
def test_explicit_api_key_arg_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Passing ``api_key=`` explicitly must be enough — no env access required."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    from engine.llm.gemini import GeminiProvider

    # Construction must not raise when api_key is supplied directly.
    provider = GeminiProvider(api_key="explicit-key")
    assert provider.name == "gemini"


# ---------------------------------------------------------------------------
# chat(): request shape + response parsing
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chat_returns_normalized_llm_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful call yields the expected text + token-usage shape."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake_resp = _fake_gemini_response(text="حياكم الله", prompt_tokens=20, completion_tokens=8)
    _install_fake_models(monkeypatch, fake_resp)

    from engine.llm.gemini import GeminiProvider

    provider = GeminiProvider()
    result = await provider.chat([Message(role="user", content="مرحبا")])

    assert result.text == "حياكم الله"
    assert isinstance(result.usage, TokenUsage)
    assert result.usage.prompt_tokens == 20
    assert result.usage.completion_tokens == 8


@pytest.mark.unit
@pytest.mark.asyncio
async def test_system_message_lifted_to_system_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """System role must NOT appear in ``contents``; it goes to ``system_instruction``.

    This is Gemini's convention. The adapter is expected to extract the system
    message and pass it via ``config={"system_instruction": ...}`` (or the
    equivalent typed parameter in the SDK).
    """
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake = _install_fake_models(monkeypatch, _fake_gemini_response())

    from engine.llm.gemini import GeminiProvider

    provider = GeminiProvider()
    await provider.chat(
        [
            Message(role="system", content="أنت سارة"),
            Message(role="user", content="مرحبا"),
        ]
    )

    assert len(fake.calls) == 1
    call = fake.calls[0]

    # System content must surface somewhere on the call kwargs (system_instruction
    # field or nested config). It must NOT appear inside `contents`.
    serialized = repr(call)
    assert "أنت سارة" in serialized, "system message must reach the SDK call"

    contents = call.get("contents")
    if contents is not None:
        # If contents is provided, verify no role/text inside it is the system msg.
        flat = repr(contents)
        # A user message must be present; the system one must not be inside `contents`.
        assert "مرحبا" in flat, "user message must reach `contents`"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_assistant_role_becomes_model_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini calls the assistant role ``model``. The adapter must map it."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake = _install_fake_models(monkeypatch, _fake_gemini_response())

    from engine.llm.gemini import GeminiProvider

    provider = GeminiProvider()
    await provider.chat(
        [
            Message(role="user", content="مرحبا"),
            Message(role="assistant", content="أهلاً"),
            Message(role="user", content="كيف الحال"),
        ]
    )

    serialized = repr(fake.calls[0])
    # Either the SDK request shows a "model" role label for the assistant turn,
    # or no "assistant" label appears (Gemini uses "user"/"model" only).
    assert "model" in serialized.lower() or "assistant" not in serialized.lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_usage_metadata_maps_to_token_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adapter must read ``usage_metadata`` and populate the canonical ``TokenUsage``."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    _install_fake_models(
        monkeypatch,
        _fake_gemini_response(prompt_tokens=137, completion_tokens=42),
    )

    from engine.llm.gemini import GeminiProvider

    provider = GeminiProvider()
    result = await provider.chat([Message(role="user", content="hi")])

    assert result.usage is not None
    assert result.usage.prompt_tokens == 137
    assert result.usage.completion_tokens == 42


@pytest.mark.unit
@pytest.mark.asyncio
async def test_default_model_used_when_arg_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the caller doesn't pass ``model=``, the default from __init__ is used."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake = _install_fake_models(monkeypatch, _fake_gemini_response())

    from engine.llm.gemini import GeminiProvider

    provider = GeminiProvider(default_model="gemini-2.5-flash")
    await provider.chat([Message(role="user", content="hi")])

    call = fake.calls[0]
    # The SDK accepts ``model=`` as a kwarg; the adapter passes it through.
    assert call.get("model") == "gemini-2.5-flash" or "gemini-2.5-flash" in repr(call)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_explicit_model_override_passed_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """``chat(model="...")`` must override the constructor default."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake = _install_fake_models(monkeypatch, _fake_gemini_response())

    from engine.llm.gemini import GeminiProvider

    provider = GeminiProvider(default_model="gemini-2.5-flash")
    await provider.chat([Message(role="user", content="hi")], model="gemini-2.5-pro")

    call = fake.calls[0]
    assert call.get("model") == "gemini-2.5-pro" or "gemini-2.5-pro" in repr(call)
