"""Turn-by-turn conversation orchestrator for the P1 chat loop.

Wires the channel-neutral ``ChannelMessage`` to the LLM provider through:

1. session lookup / creation (in-memory in P1, Redis in P2)
2. system-prompt assembly via :class:`SystemPromptBuilder`
3. message-list construction from the recent turn buffer
4. LLM call (provider-agnostic, via the ``LLMProvider`` ABC)
5. session update with the assistant turn
6. lightweight response-length sanity check (a soft warning in P1; the full
   correction-retry loop lands in P4)

Special commands (``/start`` and ``/teach``) are intercepted before the LLM
call. The ``/teach`` handler here is a stub — the full implementation that
persists corrections to Postgres and re-runs the dialect eval lands in P4.
"""

from __future__ import annotations

from typing import Literal, Protocol, cast, runtime_checkable

import structlog

from engine.config.schema import BusinessConfig
from engine.core.types import (
    ChannelMessage,
    LLMResponse,
    Role,
    ToolSchema,
    Turn,
)
from engine.llm.base import Message
from engine.memory.short_term import InMemorySessionStore
from engine.prompts.system_builder import SystemPromptBuilder

__all__ = ["LLMProvider", "Orchestrator"]

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# LLMProvider protocol
# ---------------------------------------------------------------------------
# The concrete ``engine.llm.base.LLMProvider`` ABC is being built in parallel
# in this same phase. To avoid a hard import-time coupling (and a circular
# risk if the LLM layer ever wants to import from ``core``), we declare a
# structural ``Protocol`` that matches the PLAN.md §3 contract. Concrete
# adapters (Gemini, Claude, OpenAI) satisfy it automatically.
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMProvider(Protocol):
    """Structural protocol matching ``engine.llm.base.LLMProvider``.

    See PLAN.md §3. The orchestrator depends only on the ``chat`` method;
    streaming, pricing, and tool-call normalization are concerns of the
    concrete adapter layer.
    """

    async def chat(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = ...,
        model: str | None = ...,
        temperature: float = ...,
        max_tokens: int = ...,
        response_format: Literal["text", "json"] = ...,
    ) -> LLMResponse:
        """Send a chat completion request and return a normalized response."""
        ...


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

# Canned replies for the early commands. Kept here (not in the template) so a
# template-render failure cannot break the basic command surface.
_TEACH_ACK = "تم استلام الملاحظة، شكراً لكم."
_ATTACHMENT_REJECT = "عذراً، حالياً نتعامل مع النصوص فقط."

# Synthetic user turn injected on ``/start`` so the LLM produces a natural
# opening greeting instead of echoing the slash command back.
_START_USER_PROMPT = "السلام عليكم — يبدأ الزبون المحادثة"

# Response-length sanity check (PLAN.md §6.8). The full retry mechanism lands
# in P4; here we just log a warning so we can see regressions in the metrics
# before the corrector is online.
_SHORT_USER_THRESHOLD_WORDS = 6
_LONG_REPLY_THRESHOLD_WORDS = 40


# ---------------------------------------------------------------------------
# orchestrator
# ---------------------------------------------------------------------------


class Orchestrator:
    """The turn-by-turn loop. Wires session → prompt → LLM → reply.

    One orchestrator instance serves all chats for a single business. State
    is held in the injected ``session_store`` (in-memory in P1, Redis in P2).
    """

    def __init__(
        self,
        config: BusinessConfig,
        llm: LLMProvider,
        session_store: InMemorySessionStore,
        system_builder: SystemPromptBuilder,
    ) -> None:
        """Initialize the orchestrator.

        Args:
            config: Validated business config (drives persona, model, etc.).
            llm: Any object satisfying the :class:`LLMProvider` protocol.
            session_store: Conversation buffer (in-memory in P1).
            system_builder: System-prompt assembler.
        """
        self._config = config
        self._llm = llm
        self._sessions = session_store
        self._builder = system_builder
        # Render the system prompt eagerly so a template error surfaces at
        # startup, not on the first user message.
        self._system_prompt = self._builder.build(config)
        log.info(
            "orchestrator.ready",
            business_id=config.business.id,
            persona=config.persona.name,
            provider=config.llm.provider,
            model=config.llm.model,
            system_prompt_chars=len(self._system_prompt),
        )

    # ------------------------------------------------------------------
    # public entrypoint
    # ------------------------------------------------------------------

    async def handle(self, msg: ChannelMessage) -> str:
        """Process one inbound message and return the reply text.

        Special handling:
          * ``/start``                — clears prior state and asks the LLM
                                         for a fresh opening greeting.
          * ``/teach …``              — acks; full handler lands in P4.
          * attachments without text  — politely rejects (text-only in P1).

        Otherwise the message is appended to the session, the LLM is called
        with the rendered system prompt plus the recent turn buffer, and the
        assistant reply is appended to the session before returning.
        """
        text = (msg.text or "").strip()

        # 1. Attachments without text — P1 is text-only.
        if not text and msg.attachments:
            log.info(
                "orchestrator.attachment_rejected",
                chat_id=msg.chat_id,
                attachment_kinds=[a.kind for a in msg.attachments],
            )
            return _ATTACHMENT_REJECT

        # 2. /teach — stub ack until P4.
        if text.startswith("/teach"):
            log.info("orchestrator.teach_stub", chat_id=msg.chat_id, raw_text=text[:200])
            return _TEACH_ACK

        # 3. /start — clear state, then prompt for a fresh greeting.
        if text == "/start":
            self._sessions.reset(msg.chat_id)
            return await self._handle_start(msg)

        # 4. Normal turn.
        return await self._handle_turn(msg, text)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    async def _handle_start(self, msg: ChannelMessage) -> str:
        """Generate a fresh opening greeting for a brand-new conversation."""
        session = self._sessions.get_or_create(msg.chat_id, self._config.business.id)
        # Synthetic user turn so the LLM has something to "respond to" without
        # the bare ``/start`` token leaking into the transcript.
        opener = Turn(role=Role.user, text=_START_USER_PROMPT)
        self._sessions.add_turn(msg.chat_id, opener)

        reply_text = await self._call_llm_for_session(msg.chat_id)
        self._sessions.add_turn(
            msg.chat_id,
            Turn(role=Role.assistant, text=reply_text),
        )
        log.info(
            "orchestrator.start",
            chat_id=msg.chat_id,
            business_id=session.business_id,
            reply_chars=len(reply_text),
        )
        return reply_text

    async def _handle_turn(self, msg: ChannelMessage, text: str) -> str:
        """Process a normal user turn through the LLM."""
        self._sessions.get_or_create(msg.chat_id, self._config.business.id)
        user_turn = Turn(role=Role.user, text=text)
        self._sessions.add_turn(msg.chat_id, user_turn)

        reply_text = await self._call_llm_for_session(msg.chat_id)
        self._sessions.add_turn(
            msg.chat_id,
            Turn(role=Role.assistant, text=reply_text),
        )

        self._length_sanity_check(user_text=text, reply_text=reply_text, chat_id=msg.chat_id)
        log.info(
            "orchestrator.turn",
            chat_id=msg.chat_id,
            user_chars=len(text),
            reply_chars=len(reply_text),
        )
        return reply_text

    async def _call_llm_for_session(self, chat_id: str) -> str:
        """Assemble messages and dispatch to the LLM provider."""
        recent = self._sessions.recent_turns(chat_id)
        messages = self._turns_to_messages(recent)

        response = await self._llm.chat(
            messages=messages,
            tools=None,
            model=self._config.llm.model,
            temperature=self._config.llm.temperature,
            max_tokens=self._config.llm.max_tokens,
            response_format="text",
        )
        reply = (response.text or "").strip()
        if not reply:
            # Defensive: an empty reply would be confusing to the user. Fall
            # back to the persona's signature close so the channel still has
            # something polite to send.
            log.warning("orchestrator.empty_llm_reply", chat_id=chat_id)
            reply = self._config.persona.signature_close
        return reply

    def _turns_to_messages(self, turns: list[Turn]) -> list[Message]:
        """Convert session turns into the provider-neutral message list.

        Returns ``list[Message]`` (engine.llm.base.Message) — the shape every
        LLMProvider adapter expects. The system prompt is always first. Tool
        turns are not emitted here — tool wiring lands in P3, so the P1
        transcript is just user / assistant alternations.
        """
        messages: list[Message] = [Message(role="system", content=self._system_prompt)]
        for turn in turns:
            if turn.role in (Role.user, Role.assistant):
                role_literal = cast(Literal["user", "assistant"], turn.role.value)
                messages.append(Message(role=role_literal, content=turn.text))
            # Role.tool / Role.system inside the transcript are ignored in P1.
        return messages

    def _length_sanity_check(self, *, user_text: str, reply_text: str, chat_id: str) -> None:
        """Log a warning when a short user message gets a long reply.

        The full corrector that retries with a stricter brevity instruction
        lands in P4 (PLAN.md §6.8). For P1 we only emit the signal so it shows
        up in logs and metrics from day one.
        """
        user_words = len(user_text.split())
        reply_words = len(reply_text.split())
        if user_words <= _SHORT_USER_THRESHOLD_WORDS and reply_words > _LONG_REPLY_THRESHOLD_WORDS:
            log.warning(
                "orchestrator.reply_too_long",
                chat_id=chat_id,
                user_words=user_words,
                reply_words=reply_words,
                threshold_user=_SHORT_USER_THRESHOLD_WORDS,
                threshold_reply=_LONG_REPLY_THRESHOLD_WORDS,
            )
