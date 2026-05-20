"""Unit tests for ``engine.core.orchestrator.Orchestrator``.

We exercise the orchestrator with a hand-written ``FakeLLMProvider`` (matching
the structural ``LLMProvider`` protocol) so the test never touches a real
network or SDK. The fake records every ``messages=`` list it was called with
so we can assert on the system prompt shape, history persistence, and the
``/start`` / ``/teach`` / attachment short-circuits.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal

import pytest

from engine.config.loader import load_business_config
from engine.config.schema import BusinessConfig
from engine.core.orchestrator import Orchestrator
from engine.core.types import (
    Attachment,
    ChannelMessage,
    LLMResponse,
    TokenUsage,
    ToolSchema,
)
from engine.llm.base import LLMDelta, LLMProvider, Message, Pricing
from engine.memory.short_term import InMemorySessionStore
from engine.prompts.system_builder import SystemPromptBuilder

# ---------------------------------------------------------------------------
# FakeLLMProvider — concrete, deterministic, never hits the network.
# Satisfies the engine.llm.base.LLMProvider ABC AND the orchestrator's
# structural protocol.
# ---------------------------------------------------------------------------


class FakeLLMProvider(LLMProvider):
    """Recording fake — returns a configurable reply every time."""

    name = "fake"

    def __init__(self, reply: str = "أهلاً وسهلاً، حياكم. كيف اقدر اخدمكم؟") -> None:
        self._reply = reply
        # The orchestrator passes raw dicts, not Message objects, so record dicts.
        self.last_messages: list[Any] | None = None
        self.last_kwargs: dict[str, Any] | None = None
        self.call_count: int = 0

    async def chat(
        self,
        messages: Any,
        *,
        tools: list[ToolSchema] | None = None,
        model: str | None = None,
        temperature: float = 0.4,
        max_tokens: int = 800,
        response_format: Literal["text", "json"] = "text",
    ) -> LLMResponse:
        # ``messages`` may be list[dict] (from the orchestrator) or list[Message]
        # (from direct LLM-layer callers). Store either way.
        self.last_messages = list(messages)
        self.last_kwargs = {
            "tools": tools,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": response_format,
        }
        self.call_count += 1
        return LLMResponse(
            text=self._reply,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=20),
        )

    async def stream(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
        model: str | None = None,
        temperature: float = 0.4,
        max_tokens: int = 800,
    ) -> AsyncIterator[LLMDelta]:
        yield LLMDelta(text=self._reply)  # pragma: no cover

    def pricing(self, model: str) -> Pricing:
        return Pricing(
            provider="fake",
            model=model,
            input_per_million_usd=0.0,
            output_per_million_usd=0.0,
        )


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def business_config(repo_root: Any) -> BusinessConfig:
    """Real ``generic_demo`` config loaded from disk."""
    return load_business_config("generic_demo", businesses_dir=repo_root / "businesses")


@pytest.fixture
def system_builder() -> SystemPromptBuilder:
    """Default builder — uses ``engine/prompts/templates``."""
    return SystemPromptBuilder()


@pytest.fixture
def session_store() -> InMemorySessionStore:
    return InMemorySessionStore(max_turns=12)


@pytest.fixture
def fake_llm() -> FakeLLMProvider:
    return FakeLLMProvider()


@pytest.fixture
def orchestrator(
    business_config: BusinessConfig,
    fake_llm: FakeLLMProvider,
    session_store: InMemorySessionStore,
    system_builder: SystemPromptBuilder,
) -> Orchestrator:
    return Orchestrator(
        config=business_config,
        llm=fake_llm,  # type: ignore[arg-type]
        session_store=session_store,
        system_builder=system_builder,
    )


def _content_of(message: Any) -> str:
    """Read the textual content from either a dict-shaped or Message-shaped entry."""
    if isinstance(message, dict):
        return str(message.get("content", ""))
    return str(getattr(message, "content", ""))


def _role_of(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role", ""))
    return str(getattr(message, "role", ""))


# ---------------------------------------------------------------------------
# /start handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_clears_state_and_returns_llm_reply(
    orchestrator: Orchestrator,
    fake_llm: FakeLLMProvider,
    session_store: InMemorySessionStore,
) -> None:
    """``/start`` resets the chat and asks the LLM for an opening greeting."""
    msg = ChannelMessage(chat_id="42", user_id="u1", text="/start")

    reply = await orchestrator.handle(msg)

    assert reply == fake_llm._reply
    assert fake_llm.call_count == 1
    # /start must have hit the LLM with the system prompt + synthetic user turn.
    assert fake_llm.last_messages is not None
    assert len(fake_llm.last_messages) >= 2
    assert _role_of(fake_llm.last_messages[0]) == "system"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_resets_prior_session_turns(
    orchestrator: Orchestrator,
    session_store: InMemorySessionStore,
) -> None:
    """Pre-existing turns for the chat are wiped on ``/start``."""
    # Pre-populate some turns under the same chat_id.
    chat_id = "99"
    await orchestrator.handle(ChannelMessage(chat_id=chat_id, text="ايوا"))
    assert len(session_store.recent_turns(chat_id)) > 0

    await orchestrator.handle(ChannelMessage(chat_id=chat_id, text="/start"))

    # After /start the session is created fresh, then a synthetic user turn and
    # the assistant reply are added by the start handler — so we expect 2 turns,
    # not the four-or-more that would accumulate without a reset.
    after = session_store.recent_turns(chat_id)
    assert 1 <= len(after) <= 2


# ---------------------------------------------------------------------------
# Normal user turn
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_normal_text_message_calls_llm_and_records_turn(
    orchestrator: Orchestrator,
    fake_llm: FakeLLMProvider,
    session_store: InMemorySessionStore,
) -> None:
    """A plain Arabic message gets a reply and accumulates two turns."""
    # First /start to seed the conversation.
    await orchestrator.handle(ChannelMessage(chat_id="1", text="/start"))
    pre_count = fake_llm.call_count

    reply = await orchestrator.handle(ChannelMessage(chat_id="1", text="ايوا"))

    assert reply == fake_llm._reply
    assert fake_llm.call_count == pre_count + 1
    # The most recent turn pair should be user="ايوا" + assistant=reply.
    turns = session_store.recent_turns("1")
    assert any(t.text == "ايوا" for t in turns)
    assert any(t.text == fake_llm._reply for t in turns)


# ---------------------------------------------------------------------------
# /teach short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_teach_command_returns_canned_ack_without_calling_llm(
    orchestrator: Orchestrator,
    fake_llm: FakeLLMProvider,
) -> None:
    """``/teach correction here`` must NOT call the LLM in P1."""
    msg = ChannelMessage(chat_id="42", text="/teach يجب أن نقول ايوا بدل إيه")

    reply = await orchestrator.handle(msg)

    # Canned ack is in Arabic and contains a "thanks" word; we don't pin the
    # exact phrasing to avoid coupling to the canned-string constant.
    assert reply
    assert isinstance(reply, str)
    assert fake_llm.call_count == 0


# ---------------------------------------------------------------------------
# Attachments-only short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_attachment_only_message_returns_canned_text_only_reply(
    orchestrator: Orchestrator,
    fake_llm: FakeLLMProvider,
) -> None:
    """Image-only / voice-only messages get a polite "text only" message."""
    msg = ChannelMessage(
        chat_id="42",
        text="",
        attachments=[Attachment(kind="image", url="file_id_123", mime="image/jpeg")],
    )

    reply = await orchestrator.handle(msg)

    assert reply
    assert isinstance(reply, str)
    assert fake_llm.call_count == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_attachment_with_caption_still_processed_as_text(
    orchestrator: Orchestrator,
    fake_llm: FakeLLMProvider,
) -> None:
    """If the message carries text *and* attachments, the text path wins."""
    msg = ChannelMessage(
        chat_id="42",
        text="ويش اقدر اعمل بالصورة؟",
        attachments=[Attachment(kind="image", url="x", mime="image/jpeg")],
    )

    reply = await orchestrator.handle(msg)

    assert reply == fake_llm._reply
    assert fake_llm.call_count == 1


# ---------------------------------------------------------------------------
# System prompt content — Omani lexicon coverage
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_system_prompt_contains_required_lexicon(
    orchestrator: Orchestrator,
    fake_llm: FakeLLMProvider,
) -> None:
    """The system prompt sent to the LLM must teach the Omani lexicon."""
    await orchestrator.handle(ChannelMessage(chat_id="1", text="/start"))

    assert fake_llm.last_messages is not None
    sys_message = fake_llm.last_messages[0]
    assert _role_of(sys_message) == "system"
    sys_text = _content_of(sys_message)

    # Required Omani forms (PLAN.md §6.3 lexicon).
    for term in ["ويش", "ايوا", "كيف الحال", "كيف اقدر اخدم", "ما مشكلة", "لو سمحت"]:
        assert term in sys_text, f"system prompt missing required lexicon term: {term!r}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_system_prompt_includes_banned_token_warnings(
    orchestrator: Orchestrator,
    fake_llm: FakeLLMProvider,
) -> None:
    """The banned forms should be listed under the "avoid" guidance.

    We're NOT asserting they're absent (they MUST be present, in the avoid
    list, so the model learns them). We only require they appear at all —
    the template hygiene check in test_system_builder verifies they're not
    accidentally promoted into the "use these" section.
    """
    await orchestrator.handle(ChannelMessage(chat_id="1", text="/start"))

    assert fake_llm.last_messages is not None
    sys_text = _content_of(fake_llm.last_messages[0])

    # At least a few banned forms should be listed (so the model learns them).
    banned_present = sum(term in sys_text for term in ["شو", "إيش", "إيه", "لو تكرم", "وايد"])
    assert banned_present >= 3, f"only {banned_present} banned forms found in prompt"


# ---------------------------------------------------------------------------
# Empty / unusual inputs
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_whitespace_only_message_still_routed_to_llm(
    orchestrator: Orchestrator,
    fake_llm: FakeLLMProvider,
) -> None:
    """An all-whitespace message with no attachments is treated as a normal turn.

    The orchestrator strips the text, so the LLM sees an empty user turn; the
    contract is that this still goes through (not silently dropped), so we
    can observe oddities in logs.
    """
    msg = ChannelMessage(chat_id="42", text="   ")
    reply = await orchestrator.handle(msg)
    # We don't pin the exact reply — only that something came back and the LLM
    # was actually consulted (no short-circuit fired).
    assert isinstance(reply, str) and reply
    assert fake_llm.call_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_llm_called_with_business_config_model_and_temperature(
    orchestrator: Orchestrator,
    fake_llm: FakeLLMProvider,
    business_config: BusinessConfig,
) -> None:
    """Model + temperature pulled from business config flow through to the LLM."""
    await orchestrator.handle(ChannelMessage(chat_id="1", text="/start"))

    assert fake_llm.last_kwargs is not None
    assert fake_llm.last_kwargs["model"] == business_config.llm.model
    assert fake_llm.last_kwargs["temperature"] == pytest.approx(business_config.llm.temperature)
