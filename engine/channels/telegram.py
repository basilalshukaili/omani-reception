"""Telegram channel adapter (long-polling, python-telegram-bot v21).

Implements :class:`engine.channels.base.Channel` for Telegram. Inbound
``telegram.Update`` events are normalized to :class:`ChannelMessage` and
dispatched to the orchestrator-supplied ``MessageHandler``. The handler may
return a string, a full ``ChannelMessage``, or ``None``.

Design notes
------------
* **Long-polling only in P1.** Webhook mode is sketched in PLAN §11 but not
  implemented here — long-poll keeps dev simple (no public URL).
* **No live Telegram calls during construction.** We validate inputs locally
  and defer all network I/O to :meth:`start`. This keeps unit tests fast and
  hermetic (mandated by the P1 brief).
* **PII discipline.** Inbound text may contain personal data, so message text
  is logged at ``DEBUG`` only. ``INFO`` lines carry just ``chat_id``,
  ``user_id``, and structural metadata.
* **Allowlist.** Empty/``None`` ⇒ allow all chats (with a startup warning so
  the operator notices). Non-empty ⇒ drop unknown chats silently, log at INFO.
* **Admin allowlist.** Independent of the chat allowlist; controls ``/teach``.
"""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

import structlog
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    filters,
)
from telegram.ext import (
    MessageHandler as TGMessageHandler,
)

from engine.channels.base import Channel, MessageHandler
from engine.core.types import Attachment, ChannelMessage

if TYPE_CHECKING:
    from telegram import Message

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Canned Arabic (Omani, official-respectful) replies for built-in flows.
# Kept inline so the channel does not depend on the phrase library yet (that
# lands with the dialect layer in P4). Each string is short by design.
# ---------------------------------------------------------------------------

_MEDIA_NOT_SUPPORTED_AR = "عذراً، حالياً نتعامل مع النصوص فقط."
_TEACH_THANKS_AR = "تم استلام الملاحظة، شكراً."
_TEACH_NOT_ADMIN_AR = "عذراً، هذا الأمر مخصص للمشرفين."
_TEACH_MISSING_AR = "الرجاء كتابة الملاحظة بعد الأمر."


class TelegramChannel(Channel):
    """Long-polling Telegram adapter.

    Parameters
    ----------
    token:
        The bot token from BotFather. Required; empty/whitespace raises.
    allowed_chat_ids:
        If non-empty, only messages from these chat ids are dispatched. If
        ``None`` or empty, every chat is allowed (a warning is logged at
        ``start`` so operators are aware).
    admin_chat_ids:
        Chats permitted to invoke admin-only commands (``/teach`` etc.). If
        ``None`` or empty, no chat is admin.
    """

    name = "telegram"

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def __init__(
        self,
        token: str,
        *,
        allowed_chat_ids: Iterable[int] | None = None,
        admin_chat_ids: Iterable[int] | None = None,
    ) -> None:
        if not token or not token.strip():
            raise ValueError(
                "TelegramChannel: bot token is empty. "
                "Set TELEGRAM_BOT_TOKEN in your .env (see HANDOFF.md)."
            )

        self._token = token
        self._allowed_chat_ids: frozenset[int] = frozenset(allowed_chat_ids or ())
        self._admin_chat_ids: frozenset[int] = frozenset(admin_chat_ids or ())

        # The orchestrator-supplied callback. Set in :meth:`start`.
        self._handler: MessageHandler | None = None

        # PTB Application is built lazily in :meth:`start` so that constructing
        # a TelegramChannel is cheap and side-effect-free (no event loop, no
        # network, no thread). Tests can poke it after calling ``_build_app``.
        # ``Application`` is a 6-parameter generic in PTB v21; the type params
        # are internal-only (bot type, context type, user/chat/bot data, job
        # queue), so we punt to ``Any`` rather than baking PTB's defaults in.
        self._app: Application[Any, Any, Any, Any, Any, Any] | None = None

        # An asyncio.Event used to keep ``start`` blocking until ``stop`` (or a
        # signal) requests teardown. Created lazily because Event binds to the
        # running event loop, and we may be constructed outside of one.
        self._stop_event: asyncio.Event | None = None

        # Track which signals we hooked so we can restore the originals on
        # shutdown. None on platforms (e.g., Windows) where add_signal_handler
        # isn't available — we fall back to KeyboardInterrupt handling.
        self._signal_handlers_installed: list[signal.Signals] = []

    # ------------------------------------------------------------------
    # Public API (engine.channels.base.Channel)
    # ------------------------------------------------------------------
    async def start(self, handler: MessageHandler) -> None:
        """Initialize PTB, install handlers, and run long-polling until stop."""
        if self._app is not None:
            raise RuntimeError("TelegramChannel.start() called twice")

        self._handler = handler
        self._stop_event = asyncio.Event()
        self._build_app()
        assert self._app is not None  # for type-checker

        if not self._allowed_chat_ids:
            logger.warning(
                "telegram.allowlist_disabled",
                detail="allowed_chat_ids is empty; ALL chats will be served",
            )

        logger.info(
            "telegram.start",
            allowed_chats=len(self._allowed_chat_ids),
            admins=len(self._admin_chat_ids),
        )

        self._install_signal_handlers()
        try:
            await self._app.initialize()
            await self._app.start()
            assert self._app.updater is not None
            await self._app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            await self._stop_event.wait()
        finally:
            await self._teardown()

    async def stop(self) -> None:
        """Signal the run loop to exit. Safe to call from any task or signal."""
        if self._stop_event is not None and not self._stop_event.is_set():
            logger.info("telegram.stop_requested")
            self._stop_event.set()

    async def send(self, chat_id: str, content: str | ChannelMessage) -> None:
        """Send a proactive message to ``chat_id`` (escalations, nudges).

        Requires :meth:`start` to have brought the PTB ``Application`` to the
        running state — otherwise the bot's HTTP client is uninitialised and
        we'd issue a live network call against a half-built bot.
        """
        if self._app is None or not self._app.running:
            raise RuntimeError(
                "TelegramChannel.send() called before start(); the channel must "
                "be running for proactive sends."
            )

        text = content if isinstance(content, str) else content.text
        await self._app.bot.send_message(chat_id=chat_id, text=text)
        logger.info("telegram.reply_sent", chat_id=str(chat_id), proactive=True)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _build_app(self) -> None:
        """Build the PTB ``Application`` and register handlers.

        Split out from :meth:`start` so unit tests can verify handler wiring
        without engaging the event loop / network.
        """
        app = Application.builder().token(self._token).build()
        app.add_handler(CommandHandler("start", self._handle_start))
        app.add_handler(CommandHandler("teach", self._handle_teach))
        app.add_handler(TGMessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))
        # Media handler covers photo, voice, audio, video, document, animation,
        # video_note, sticker — anything non-text that arrives in a Message.
        media_filter = (
            filters.PHOTO
            | filters.VOICE
            | filters.AUDIO
            | filters.VIDEO
            | filters.Document.ALL
            | filters.ANIMATION
            | filters.VIDEO_NOTE
            | filters.Sticker.ALL
        )
        app.add_handler(TGMessageHandler(media_filter, self._handle_media))
        # Catch-all error handler keeps the polling loop alive across bugs.
        app.add_error_handler(self._handle_error)
        self._app = app

    def _install_signal_handlers(self) -> None:
        """Wire SIGINT/SIGTERM to ``stop`` on POSIX.

        ``loop.add_signal_handler`` is not implemented on Windows; PTB's own
        polling layer will still raise ``KeyboardInterrupt`` on Ctrl-C there,
        which we let propagate.
        """
        loop = asyncio.get_running_loop()
        for sig_name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))
            except (NotImplementedError, RuntimeError):
                # Windows or non-main thread: skip silently.
                continue
            self._signal_handlers_installed.append(sig)

    def _remove_signal_handlers(self) -> None:
        """Best-effort removal of any signal handlers we installed."""
        if not self._signal_handlers_installed:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        for sig in self._signal_handlers_installed:
            try:
                loop.remove_signal_handler(sig)
            except (NotImplementedError, RuntimeError):
                continue
        self._signal_handlers_installed.clear()

    async def _teardown(self) -> None:
        """Symmetric counterpart to startup; idempotent and exception-tolerant."""
        self._remove_signal_handlers()
        if self._app is None:
            return
        try:
            if self._app.updater is not None and self._app.updater.running:
                await self._app.updater.stop()
            if self._app.running:
                await self._app.stop()
            await self._app.shutdown()
        except Exception:  # pragma: no cover — shutdown errors are non-fatal
            logger.exception("telegram.shutdown_error")
        finally:
            logger.info("telegram.stop")

    # ------------------------------------------------------------------
    # Handlers (PTB callbacks)
    # ------------------------------------------------------------------
    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """``/start`` — dispatched to the orchestrator with command metadata."""
        msg = self._update_to_channel_message(update, command="start")
        if msg is None:
            return
        if not self._is_chat_allowed(int(msg.chat_id)):
            self._log_unauthorized(msg.chat_id, "start")
            return
        await self._dispatch_and_reply(update, msg)

    async def _handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Plain-text messages → ``ChannelMessage`` → orchestrator."""
        msg = self._update_to_channel_message(update)
        if msg is None:
            return
        if not self._is_chat_allowed(int(msg.chat_id)):
            self._log_unauthorized(msg.chat_id, "text")
            return
        await self._dispatch_and_reply(update, msg)

    async def _handle_media(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Non-text payloads — wrap as ``Attachment`` and acknowledge politely.

        P1 does not process media; we surface the message to the orchestrator
        (so it shows up in transcripts/observability) but always reply with the
        canned Arabic 'text only' notice rather than what the handler returns.
        """
        msg = self._update_to_channel_message(update)
        if msg is None:
            return
        if not self._is_chat_allowed(int(msg.chat_id)):
            self._log_unauthorized(msg.chat_id, "media")
            return
        logger.info(
            "telegram.message_received",
            chat_id=msg.chat_id,
            user_id=msg.user_id,
            kind="media",
            attachments=[a.kind for a in msg.attachments],
        )
        # Best-effort: let the orchestrator know (it may want to log/store the
        # event), but ignore whatever it returns. The user gets the canned
        # apology so they're never left wondering.
        if self._handler is not None:
            try:
                await self._handler(msg)
            except Exception:  # pragma: no cover
                logger.exception("telegram.handler_error", chat_id=msg.chat_id)
        if update.message is not None:
            await update.message.reply_text(_MEDIA_NOT_SUPPORTED_AR)
            logger.info("telegram.reply_sent", chat_id=msg.chat_id, kind="media_ack")

    async def _handle_teach(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """``/teach <correction>`` — admin-only dialect correction intake (P4).

        For P1 we just log the correction and acknowledge in Omani. The actual
        persistence + ``scripts/apply_corrections.py`` workflow lands in P4.
        """
        if update.message is None or update.message.from_user is None:
            return
        chat_id = update.message.chat_id
        if not self._is_admin(chat_id):
            self._log_unauthorized(str(chat_id), "teach")
            await update.message.reply_text(_TEACH_NOT_ADMIN_AR)
            return
        # context.args is the tokenised payload; rebuild the raw text for fidelity.
        correction = " ".join(context.args).strip() if context.args else ""
        if not correction:
            await update.message.reply_text(_TEACH_MISSING_AR)
            return
        logger.info(
            "telegram.teach_received",
            chat_id=str(chat_id),
            user_id=str(update.message.from_user.id),
            length=len(correction),
        )
        logger.debug("telegram.teach_payload", chat_id=str(chat_id), correction=correction)
        await update.message.reply_text(_TEACH_THANKS_AR)
        logger.info("telegram.reply_sent", chat_id=str(chat_id), kind="teach_ack")

    async def _handle_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """PTB error hook — log without crashing the polling loop."""
        logger.error(
            "telegram.handler_error",
            error=str(context.error) if context.error is not None else None,
        )

    # ------------------------------------------------------------------
    # Dispatch helpers
    # ------------------------------------------------------------------
    async def _dispatch_and_reply(self, update: Update, msg: ChannelMessage) -> None:
        """Run the orchestrator handler and send whatever it returned."""
        assert update.message is not None  # all dispatchers pre-check this
        if self._handler is None:  # pragma: no cover — start() always sets it
            return
        logger.info(
            "telegram.message_received",
            chat_id=msg.chat_id,
            user_id=msg.user_id,
            command=msg.metadata.get("command"),
            kind="text",
        )
        logger.debug("telegram.message_text", chat_id=msg.chat_id, text=msg.text)
        try:
            reply = await self._handler(msg)
        except Exception:
            logger.exception("telegram.handler_error", chat_id=msg.chat_id)
            return
        if reply is None:
            return
        reply_text = reply if isinstance(reply, str) else reply.text
        if not reply_text:
            return
        await update.message.reply_text(reply_text)
        logger.info("telegram.reply_sent", chat_id=msg.chat_id, kind="text")

    # ------------------------------------------------------------------
    # Allowlist / admin helpers
    # ------------------------------------------------------------------
    def _is_chat_allowed(self, chat_id: int) -> bool:
        """Empty allowlist ⇒ open. Non-empty ⇒ membership test."""
        return not self._allowed_chat_ids or chat_id in self._allowed_chat_ids

    def _is_admin(self, chat_id: int) -> bool:
        return chat_id in self._admin_chat_ids

    def _log_unauthorized(self, chat_id: str | int, kind: str) -> None:
        logger.info("telegram.unauthorized", chat_id=str(chat_id), kind=kind)

    # ------------------------------------------------------------------
    # Update → ChannelMessage conversion
    # ------------------------------------------------------------------
    def _update_to_channel_message(
        self, update: Update, *, command: str | None = None
    ) -> ChannelMessage | None:
        """Convert a PTB ``Update`` into our normalized ``ChannelMessage``.

        Returns ``None`` if the update carries no usable message (e.g.,
        ``edited_message``-only payloads, callback queries, etc., none of
        which P1 handles).
        """
        msg: Message | None = update.message
        if msg is None or msg.from_user is None:
            return None

        text = msg.text or msg.caption or ""
        attachments = _collect_attachments(msg)

        metadata: dict[str, object] = {
            "username": msg.from_user.username,
            "first_name": msg.from_user.first_name,
            "language_code": msg.from_user.language_code,
            "telegram_message_id": msg.message_id,
        }
        if command is not None:
            metadata["command"] = command

        return ChannelMessage(
            chat_id=str(msg.chat_id),
            user_id=str(msg.from_user.id),
            text=text,
            attachments=attachments,
            metadata=metadata,
            received_at=msg.date,
        )


# ---------------------------------------------------------------------------
# Module-level helpers (pure, easily unit-testable)
# ---------------------------------------------------------------------------
def _collect_attachments(msg: Message) -> list[Attachment]:
    """Translate Telegram media fields into ``Attachment`` records.

    P1 stores Telegram ``file_id`` in ``url`` (no download). Voice/audio are
    represented as ``kind="audio"``; everything else (document/video) is
    ``kind="file"`` — matching the existing ``Attachment.kind`` Literal.
    """
    attachments: list[Attachment] = []

    if msg.photo:
        largest = msg.photo[-1]  # highest-resolution PhotoSize
        attachments.append(Attachment(kind="image", url=largest.file_id, mime="image/jpeg"))
    if msg.voice is not None:
        attachments.append(
            Attachment(kind="audio", url=msg.voice.file_id, mime=msg.voice.mime_type)
        )
    if msg.audio is not None:
        attachments.append(
            Attachment(kind="audio", url=msg.audio.file_id, mime=msg.audio.mime_type)
        )
    if msg.video is not None:
        attachments.append(Attachment(kind="file", url=msg.video.file_id, mime=msg.video.mime_type))
    if msg.document is not None:
        attachments.append(
            Attachment(kind="file", url=msg.document.file_id, mime=msg.document.mime_type)
        )
    if msg.animation is not None:
        attachments.append(
            Attachment(kind="file", url=msg.animation.file_id, mime=msg.animation.mime_type)
        )
    if msg.video_note is not None:
        attachments.append(Attachment(kind="file", url=msg.video_note.file_id))
    if msg.sticker is not None:
        attachments.append(Attachment(kind="image", url=msg.sticker.file_id))

    return attachments


__all__ = ["TelegramChannel"]
