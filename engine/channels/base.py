"""Channel ABC — the bidirectional chat-channel seam.

A ``Channel`` adapts an external messaging surface (Telegram now, voice later)
to the engine's neutral ``ChannelMessage`` shape. The orchestrator stays
channel-agnostic: it just hands the channel a ``MessageHandler`` callback that
receives inbound messages and returns the reply (or ``None`` for silence).

Voice will reuse this interface: incoming audio arrives as a ``ChannelMessage``
with an audio ``Attachment``; the orchestrator runs STT, generates a reply,
and the voice channel runs TTS on the outbound side. No engine-core changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from engine.core.types import ChannelMessage

MessageHandler = Callable[[ChannelMessage], Awaitable[str | ChannelMessage | None]]
"""Async callback the channel invokes for every inbound message.

The handler returns:
  * ``str``            — reply text; the channel wraps it for sending.
  * ``ChannelMessage`` — full reply (used when attachments / metadata matter).
  * ``None``           — no reply (e.g., the message was filtered or
                          handled out-of-band).
"""


class Channel(ABC):
    """Abstract bidirectional chat channel.

    Concrete subclasses implement transport-specific I/O (long-polling,
    webhooks, WebSockets, voice gateway, etc.) while the orchestrator only
    deals with ``ChannelMessage``.
    """

    name: str
    """Stable channel identifier, e.g. ``"telegram"`` or ``"voice"``.

    Used in logs, traces, and the persisted session record so the orchestrator
    can disambiguate concurrent channels for the same user identity.
    """

    @abstractmethod
    async def start(self, handler: MessageHandler) -> None:
        """Start receiving messages and dispatch each to ``handler``.

        Blocks until :meth:`stop` is called (or a termination signal arrives).
        Implementations should drain in-flight messages on shutdown.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Request a graceful shutdown.

        Safe to call from a signal handler or another task. Must be idempotent:
        calling ``stop`` twice (or before ``start``) must not raise.
        """

    @abstractmethod
    async def send(self, chat_id: str, content: str | ChannelMessage) -> None:
        """Send a message proactively (escalations, scheduled nudges, etc.).

        ``chat_id`` is the channel-native identifier (e.g., Telegram chat id).
        ``content`` is either a plain string or a full ``ChannelMessage`` whose
        attachments and metadata the channel may honour where supported.
        """


__all__ = ["Channel", "MessageHandler"]
