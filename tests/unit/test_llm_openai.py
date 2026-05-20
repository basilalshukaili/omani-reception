"""Unit tests for ``engine.llm.openai_provider.OpenAIProvider``.

Mocking strategy
----------------
We patch ``AsyncCompletions.create`` directly on the OpenAI SDK class. The
SDK is built on ``httpx`` and ``pytest-httpx`` would also work, but
method-level patching keeps the assertions about *which messages we pass*
clean and avoids coupling to the SDK's wire encoding.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from engine.core.types import TokenUsage
from engine.llm.base import Message, MissingAPIKey


def _fake_openai_text_response(
    *,
    text: str = "أهلاً",
    prompt_tokens: int = 14,
    completion_tokens: int = 6,
) -> SimpleNamespace:
    """Build a stub mimicking ``openai.types.chat.ChatCompletion``.

    The adapter reads ``choices[0].message.content`` for text and
    ``usage.{prompt_tokens, completion_tokens}`` for accounting.
    """
    message = SimpleNamespace(role="assistant", content=text, tool_calls=None)
    choice = SimpleNamespace(index=0, message=message, finish_reason="stop")
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    return SimpleNamespace(
        id="chatcmpl-test",
        object="chat.completion",
        created=0,
        model="gpt-4o-mini",
        choices=[choice],
        usage=usage,
    )


def _fake_openai_tool_call_response(
    *,
    tool_name: str = "book_appointment",
    arguments: dict[str, Any] | None = None,
) -> SimpleNamespace:
    """Build a stub response carrying a single tool call."""
    function = SimpleNamespace(
        name=tool_name,
        arguments=json.dumps(arguments or {"when": "tomorrow", "service": "haircut"}),
    )
    tool_call = SimpleNamespace(
        id="call_abc123",
        type="function",
        function=function,
    )
    message = SimpleNamespace(role="assistant", content=None, tool_calls=[tool_call])
    choice = SimpleNamespace(index=0, message=message, finish_reason="tool_calls")
    usage = SimpleNamespace(prompt_tokens=20, completion_tokens=10, total_tokens=30)
    return SimpleNamespace(
        id="chatcmpl-tool",
        object="chat.completion",
        created=0,
        model="gpt-4o-mini",
        choices=[choice],
        usage=usage,
    )


class _CapturingCreate:
    """Async stub for ``client.chat.completions.create``."""

    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


def _install_fake_completions(monkeypatch: pytest.MonkeyPatch, response: Any) -> _CapturingCreate:
    fake = _CapturingCreate(response)
    from openai.resources.chat.completions import AsyncCompletions

    monkeypatch.setattr(AsyncCompletions, "create", fake, raising=True)
    return fake


# ---------------------------------------------------------------------------
# API-key handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_openai_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    from engine.llm.openai import OpenAIProvider

    with pytest.raises(MissingAPIKey):
        provider = OpenAIProvider()
        await provider.chat([Message(role="user", content="hi")])


@pytest.mark.unit
def test_explicit_api_key_arg_works(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    from engine.llm.openai import OpenAIProvider

    provider = OpenAIProvider(api_key="explicit-key")
    assert provider.name == "openai"


# ---------------------------------------------------------------------------
# Request shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_system_message_stays_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAI keeps the system role inline in the ``messages`` array (its own convention)."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    fake = _install_fake_completions(monkeypatch, _fake_openai_text_response())

    from engine.llm.openai import OpenAIProvider

    provider = OpenAIProvider()
    await provider.chat(
        [
            Message(role="system", content="أنت سارة"),
            Message(role="user", content="مرحبا"),
        ]
    )

    call = fake.calls[0]
    # OpenAI must NOT have a top-level ``system`` kwarg.
    assert "system" not in call

    messages = call["messages"]
    roles = [m["role"] if isinstance(m, dict) else getattr(m, "role", None) for m in messages]
    assert roles[0] == "system"
    # The system content stays in the messages array
    sys_content = messages[0]["content"] if isinstance(messages[0], dict) else messages[0].content
    assert "أنت سارة" in sys_content


@pytest.mark.unit
@pytest.mark.asyncio
async def test_temperature_and_max_tokens_passed_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    fake = _install_fake_completions(monkeypatch, _fake_openai_text_response())

    from engine.llm.openai import OpenAIProvider

    provider = OpenAIProvider()
    await provider.chat(
        [Message(role="user", content="hi")],
        temperature=0.3,
        max_tokens=400,
    )

    call = fake.calls[0]
    assert call.get("temperature") == pytest.approx(0.3)
    # max_tokens may be passed as ``max_tokens`` or the newer ``max_completion_tokens``.
    assert call.get("max_tokens") == 400 or call.get("max_completion_tokens") == 400


@pytest.mark.unit
@pytest.mark.asyncio
async def test_default_model_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    fake = _install_fake_completions(monkeypatch, _fake_openai_text_response())

    from engine.llm.openai import OpenAIProvider

    provider = OpenAIProvider(default_model="gpt-4o-mini")
    await provider.chat([Message(role="user", content="hi")])

    assert fake.calls[0].get("model") == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chat_extracts_text_and_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _install_fake_completions(
        monkeypatch,
        _fake_openai_text_response(text="حياكم", prompt_tokens=21, completion_tokens=4),
    )

    from engine.llm.openai import OpenAIProvider

    provider = OpenAIProvider()
    result = await provider.chat([Message(role="user", content="hi")])

    assert result.text == "حياكم"
    assert isinstance(result.usage, TokenUsage)
    assert result.usage.prompt_tokens == 21
    assert result.usage.completion_tokens == 4


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tool_call_response_parsed_to_canonical(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the model returns a tool call, it must surface as a canonical ``ToolCall``."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _install_fake_completions(
        monkeypatch,
        _fake_openai_tool_call_response(
            tool_name="book_appointment",
            arguments={"service": "haircut", "when": "tomorrow"},
        ),
    )

    from engine.llm.openai import OpenAIProvider

    provider = OpenAIProvider()
    result = await provider.chat([Message(role="user", content="book me in")])

    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc.name == "book_appointment"
    assert tc.arguments == {"service": "haircut", "when": "tomorrow"}
    assert tc.id == "call_abc123"
