"""Unit tests for ``engine.llm.claude.ClaudeProvider``.

Mocking strategy
----------------
The Anthropic SDK is built on ``httpx`` and is generally well-behaved under
``pytest-httpx``. For consistency with the Gemini tests (and to keep the
assertions about *what the adapter sends* easy to read) we patch
``AsyncAnthropic.messages.create`` directly. This gives us a record of the
exact kwargs the adapter constructs without coupling to the SDK's wire
encoding.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from engine.core.types import TokenUsage
from engine.llm.base import Message, MissingAPIKey


def _fake_claude_response(
    *,
    text: str = "أهلاً",
    input_tokens: int = 12,
    output_tokens: int = 9,
) -> SimpleNamespace:
    """Build a stub mimicking ``anthropic.types.Message``.

    Real responses expose ``content`` as a list of ``TextBlock`` / ``ToolUseBlock``
    objects with ``.type`` and ``.text`` / ``.input``. The adapter is expected
    to walk that list.
    """
    block = SimpleNamespace(type="text", text=text)
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    return SimpleNamespace(
        id="msg_test",
        type="message",
        role="assistant",
        model="claude-sonnet-4-6",
        content=[block],
        stop_reason="end_turn",
        usage=usage,
    )


class _CapturingCreate:
    """Async stub for ``client.messages.create``."""

    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


def _install_fake_messages(monkeypatch: pytest.MonkeyPatch, response: Any) -> _CapturingCreate:
    """Patch ``AsyncMessages.create`` on the SDK class itself."""
    fake = _CapturingCreate(response)
    # Anthropic puts the create endpoint on a per-client ``AsyncMessages``
    # instance. Patch the class method so any new provider/client picks it up.
    from anthropic.resources.messages import AsyncMessages

    monkeypatch.setattr(AsyncMessages, "create", fake, raising=True)
    return fake


# ---------------------------------------------------------------------------
# API-key handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_anthropic_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without ``ANTHROPIC_API_KEY``, construction or first call raises."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from engine.llm.claude import ClaudeProvider

    with pytest.raises(MissingAPIKey):
        provider = ClaudeProvider()
        await provider.chat([Message(role="user", content="hi")])


@pytest.mark.unit
def test_explicit_api_key_arg_works(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from engine.llm.claude import ClaudeProvider

    provider = ClaudeProvider(api_key="explicit-key")
    assert provider.name == "claude"


# ---------------------------------------------------------------------------
# Request shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_system_message_lifted_to_top_level_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anthropic's ``system`` is a top-level kwarg, not a message in the list."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    fake = _install_fake_messages(monkeypatch, _fake_claude_response())

    from engine.llm.claude import ClaudeProvider

    provider = ClaudeProvider()
    await provider.chat(
        [
            Message(role="system", content="أنت سارة"),
            Message(role="user", content="مرحبا"),
            Message(role="assistant", content="أهلاً"),
        ]
    )

    assert len(fake.calls) == 1
    call = fake.calls[0]

    # The system string should land in the top-level ``system`` field.
    system_val = call.get("system")
    assert system_val is not None
    assert "أنت سارة" in (system_val if isinstance(system_val, str) else repr(system_val))

    messages = call.get("messages") or []
    # No message in the list should have role="system".
    for m in messages:
        role = m["role"] if isinstance(m, dict) else getattr(m, "role", None)
        assert role != "system"

    # User and assistant turns should both be there.
    rendered = repr(messages)
    assert "مرحبا" in rendered
    assert "أهلاً" in rendered


@pytest.mark.unit
@pytest.mark.asyncio
async def test_max_tokens_and_temperature_passed_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    fake = _install_fake_messages(monkeypatch, _fake_claude_response())

    from engine.llm.claude import ClaudeProvider

    provider = ClaudeProvider()
    await provider.chat(
        [Message(role="user", content="hi")],
        temperature=0.2,
        max_tokens=512,
    )

    call = fake.calls[0]
    assert call.get("max_tokens") == 512
    assert call.get("temperature") == pytest.approx(0.2)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_default_model_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    fake = _install_fake_messages(monkeypatch, _fake_claude_response())

    from engine.llm.claude import ClaudeProvider

    provider = ClaudeProvider(default_model="claude-sonnet-4-6")
    await provider.chat([Message(role="user", content="hi")])

    call = fake.calls[0]
    assert call.get("model") == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chat_extracts_text_and_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    _install_fake_messages(
        monkeypatch,
        _fake_claude_response(text="حياكم الله", input_tokens=33, output_tokens=11),
    )

    from engine.llm.claude import ClaudeProvider

    provider = ClaudeProvider()
    result = await provider.chat([Message(role="user", content="hi")])

    assert result.text == "حياكم الله"
    assert isinstance(result.usage, TokenUsage)
    assert result.usage.prompt_tokens == 33
    assert result.usage.completion_tokens == 11


@pytest.mark.unit
@pytest.mark.asyncio
async def test_multiple_text_blocks_concatenated(monkeypatch: pytest.MonkeyPatch) -> None:
    """If Anthropic returns multiple text blocks they must concatenate cleanly."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    block_a = SimpleNamespace(type="text", text="الجزء الأول. ")
    block_b = SimpleNamespace(type="text", text="الجزء الثاني.")
    resp = SimpleNamespace(
        id="msg",
        type="message",
        role="assistant",
        model="claude-sonnet-4-6",
        content=[block_a, block_b],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=5, output_tokens=4),
    )
    _install_fake_messages(monkeypatch, resp)

    from engine.llm.claude import ClaudeProvider

    provider = ClaudeProvider()
    result = await provider.chat([Message(role="user", content="hi")])

    assert "الجزء الأول" in result.text
    assert "الجزء الثاني" in result.text
