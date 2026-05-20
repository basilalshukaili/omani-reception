"""Unit tests for ``engine.channels.telegram.TelegramChannel``.

We never engage the event loop or network. The strategy is to:

* Construct the channel and immediately assert no side effects happened.
* Drive ``_build_app`` (which is split out exactly for this purpose) and
  inspect the resulting ``Application`` via mocked builder/handlers.
* Build stub PTB ``Update`` objects from ``unittest.mock.MagicMock`` and feed
  them into ``_update_to_channel_message`` to verify the conversion logic.
* Verify allowlist enforcement via ``_is_chat_allowed`` plus a full handler
  call where the dispatched message comes from a disallowed chat.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engine.channels.telegram import TelegramChannel
from engine.core.types import Attachment, ChannelMessage

# ---------------------------------------------------------------------------
# Stub Update factory
# ---------------------------------------------------------------------------


def _make_stub_update(
    *,
    chat_id: int = 42,
    user_id: int = 1001,
    username: str = "tester",
    first_name: str = "Tester",
    language_code: str = "ar",
    text: str | None = "ايوا",
    photo: bool = False,
    voice: bool = False,
    document: bool = False,
    received_at: datetime | None = None,
) -> MagicMock:
    """Build a ``telegram.Update``-shaped MagicMock for unit-test consumption.

    Only fields the channel reads are populated; everything else stays as the
    default MagicMock auto-attr (which is fine because nothing here calls
    methods on those fields).
    """
    user = MagicMock()
    user.id = user_id
    user.username = username
    user.first_name = first_name
    user.language_code = language_code

    msg = MagicMock()
    msg.chat_id = chat_id
    msg.message_id = 7
    msg.from_user = user
    msg.text = text
    msg.caption = None
    msg.date = received_at or datetime.now(UTC)

    # All media attributes default to None unless set below.
    msg.photo = None
    msg.voice = None
    msg.audio = None
    msg.video = None
    msg.document = None
    msg.animation = None
    msg.video_note = None
    msg.sticker = None

    if photo:
        photo_size = MagicMock(file_id="photo_file_id_xyz")
        msg.photo = [photo_size]
    if voice:
        msg.voice = MagicMock(file_id="voice_file_id", mime_type="audio/ogg")
    if document:
        msg.document = MagicMock(file_id="doc_file_id", mime_type="application/pdf")

    update = MagicMock()
    update.message = msg
    return update


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_constructor_does_not_make_network_calls() -> None:
    """Constructing the channel must be cheap and side-effect-free."""
    # patch the Application builder; if construction touched it, the patch would
    # register a call which we then assert is absent.
    with patch("engine.channels.telegram.Application") as app_mod:
        TelegramChannel("fake-token")
        app_mod.builder.assert_not_called()


@pytest.mark.unit
def test_constructor_records_inputs() -> None:
    ch = TelegramChannel(
        "fake-token",
        allowed_chat_ids=[123, 456],
        admin_chat_ids=[123],
    )
    assert ch.name == "telegram"
    # Internal state shape isn't part of the public contract, but these are
    # private attrs used by the dispatcher logic; if their names change, the
    # rest of the suite will also need updates.
    assert ch._allowed_chat_ids == frozenset({123, 456})
    assert ch._admin_chat_ids == frozenset({123})


@pytest.mark.unit
@pytest.mark.parametrize("bad_token", ["", "   ", "\t\n"])
def test_constructor_rejects_empty_token(bad_token: str) -> None:
    with pytest.raises(ValueError):
        TelegramChannel(bad_token)


@pytest.mark.unit
def test_constructor_allows_none_allowlists() -> None:
    """``None`` for allowlist / admin list is a valid open-by-default config."""
    ch = TelegramChannel("fake-token", allowed_chat_ids=None, admin_chat_ids=None)
    assert ch._allowed_chat_ids == frozenset()
    assert ch._admin_chat_ids == frozenset()


# ---------------------------------------------------------------------------
# _update_to_channel_message
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_text_update_to_channel_message() -> None:
    ch = TelegramChannel("fake-token")
    update = _make_stub_update(text="مرحبا")

    cm = ch._update_to_channel_message(update)

    assert cm is not None
    assert isinstance(cm, ChannelMessage)
    assert cm.chat_id == "42"
    assert cm.user_id == "1001"
    assert cm.text == "مرحبا"
    assert cm.attachments == []
    # metadata round-trips Telegram-specific bits
    assert cm.metadata.get("username") == "tester"
    assert cm.metadata.get("first_name") == "Tester"
    assert cm.metadata.get("language_code") == "ar"
    assert cm.metadata.get("telegram_message_id") == 7


@pytest.mark.unit
def test_command_metadata_propagated() -> None:
    ch = TelegramChannel("fake-token")
    update = _make_stub_update(text="/start")

    cm = ch._update_to_channel_message(update, command="start")

    assert cm is not None
    assert cm.metadata.get("command") == "start"


@pytest.mark.unit
def test_no_message_returns_none() -> None:
    """Updates without a message (e.g., callback queries) yield ``None``."""
    ch = TelegramChannel("fake-token")
    update = MagicMock()
    update.message = None

    assert ch._update_to_channel_message(update) is None


@pytest.mark.unit
def test_no_from_user_returns_none() -> None:
    """Anonymous channel posts have no ``from_user`` — the channel ignores them."""
    ch = TelegramChannel("fake-token")
    update = _make_stub_update()
    update.message.from_user = None

    assert ch._update_to_channel_message(update) is None


# ---------------------------------------------------------------------------
# Attachment translation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_photo_only_message_becomes_image_attachment() -> None:
    ch = TelegramChannel("fake-token")
    update = _make_stub_update(text=None, photo=True)

    cm = ch._update_to_channel_message(update)

    assert cm is not None
    assert cm.text == ""
    assert len(cm.attachments) == 1
    att = cm.attachments[0]
    assert isinstance(att, Attachment)
    assert att.kind == "image"
    assert att.url == "photo_file_id_xyz"


@pytest.mark.unit
def test_voice_message_becomes_audio_attachment() -> None:
    ch = TelegramChannel("fake-token")
    update = _make_stub_update(text=None, voice=True)

    cm = ch._update_to_channel_message(update)

    assert cm is not None
    assert cm.text == ""
    assert len(cm.attachments) == 1
    assert cm.attachments[0].kind == "audio"
    assert cm.attachments[0].url == "voice_file_id"
    assert cm.attachments[0].mime == "audio/ogg"


@pytest.mark.unit
def test_document_message_becomes_file_attachment() -> None:
    ch = TelegramChannel("fake-token")
    update = _make_stub_update(text=None, document=True)

    cm = ch._update_to_channel_message(update)

    assert cm is not None
    assert len(cm.attachments) == 1
    assert cm.attachments[0].kind == "file"
    assert cm.attachments[0].url == "doc_file_id"


@pytest.mark.unit
def test_caption_used_when_text_absent() -> None:
    ch = TelegramChannel("fake-token")
    update = _make_stub_update(text=None, photo=True)
    update.message.caption = "وصف الصورة"

    cm = ch._update_to_channel_message(update)

    assert cm is not None
    assert cm.text == "وصف الصورة"


# ---------------------------------------------------------------------------
# Allowlist enforcement
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_allowlist_empty_means_allow_all() -> None:
    ch = TelegramChannel("fake-token", allowed_chat_ids=[])
    assert ch._is_chat_allowed(9999) is True


@pytest.mark.unit
def test_allowlist_admits_listed_chats() -> None:
    ch = TelegramChannel("fake-token", allowed_chat_ids=[42, 99])
    assert ch._is_chat_allowed(42) is True
    assert ch._is_chat_allowed(99) is True


@pytest.mark.unit
def test_allowlist_rejects_unlisted_chats() -> None:
    ch = TelegramChannel("fake-token", allowed_chat_ids=[42])
    assert ch._is_chat_allowed(123) is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_disallowed_text_message_is_dropped_without_handler_call() -> None:
    """Inbound text from a disallowed chat must NOT call the orchestrator."""
    ch = TelegramChannel("fake-token", allowed_chat_ids=[1])
    handler = AsyncMock()
    ch._handler = handler  # bypass start() wiring

    update = _make_stub_update(chat_id=999, text="hi")
    context = MagicMock()

    await ch._handle_text(update, context)

    handler.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_allowed_text_message_invokes_handler() -> None:
    ch = TelegramChannel("fake-token", allowed_chat_ids=[42])
    handler = AsyncMock(return_value="مرحبا")
    ch._handler = handler
    update = _make_stub_update(chat_id=42, text="hi")
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await ch._handle_text(update, context)

    handler.assert_awaited_once()
    update.message.reply_text.assert_awaited_once_with("مرحبا")


# ---------------------------------------------------------------------------
# Handler wiring (via _build_app)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_build_app_registers_command_and_message_handlers() -> None:
    """``_build_app`` must wire /start, /teach, text, media, and error hooks."""
    ch = TelegramChannel("fake-token", admin_chat_ids=[1])

    # Build a chain of mocks for Application.builder().token().build()
    fake_app = MagicMock()
    fake_app.add_handler = MagicMock()
    fake_app.add_error_handler = MagicMock()
    fake_builder = MagicMock()
    fake_builder.token.return_value = fake_builder
    fake_builder.build.return_value = fake_app

    with patch("engine.channels.telegram.Application") as app_mod:
        app_mod.builder.return_value = fake_builder

        ch._build_app()

        app_mod.builder.assert_called_once()
        fake_builder.token.assert_called_once_with("fake-token")
        fake_builder.build.assert_called_once()
        # At least two CommandHandler + 2 MessageHandler registrations expected.
        assert fake_app.add_handler.call_count >= 4
        fake_app.add_error_handler.assert_called_once()
        assert ch._app is fake_app


# ---------------------------------------------------------------------------
# /teach handler
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_teach_from_non_admin_rejected() -> None:
    """``/teach`` from a non-admin must reply with the not-admin message."""
    ch = TelegramChannel("fake-token", admin_chat_ids=[1])

    update = _make_stub_update(chat_id=999, text="/teach something")
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["something"]

    await ch._handle_teach(update, context)

    update.message.reply_text.assert_awaited_once()
    sent = update.message.reply_text.await_args.args[0]
    assert isinstance(sent, str) and sent


@pytest.mark.unit
@pytest.mark.asyncio
async def test_teach_from_admin_with_payload_acks() -> None:
    """``/teach <correction>`` from an admin returns the canned thanks string."""
    ch = TelegramChannel("fake-token", admin_chat_ids=[42])

    update = _make_stub_update(chat_id=42, text="/teach use ايوا instead of إيه")
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["use", "ايوا", "instead", "of", "إيه"]

    await ch._handle_teach(update, context)

    update.message.reply_text.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_teach_with_empty_payload_replies_with_missing_message() -> None:
    """``/teach`` alone with no payload must prompt for content, not crash."""
    ch = TelegramChannel("fake-token", admin_chat_ids=[42])

    update = _make_stub_update(chat_id=42, text="/teach")
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = []

    await ch._handle_teach(update, context)

    update.message.reply_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# stop() is safe before start()
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_before_start_is_safe() -> None:
    """Calling stop() without a prior start() must not raise."""
    ch = TelegramChannel("fake-token")
    # No stop_event yet, no app — the call should be a quiet no-op.
    await ch.stop()


# ---------------------------------------------------------------------------
# send() without start() raises
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_before_start_raises() -> None:
    ch = TelegramChannel("fake-token")
    with pytest.raises(RuntimeError):
        await ch.send("42", "hi")


# ---------------------------------------------------------------------------
# _handle_media short-circuits with canned reject
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_media_message_replies_with_canned_text() -> None:
    """A photo-only message must always reply with the text-only notice."""
    ch = TelegramChannel("fake-token")
    handler = AsyncMock(return_value="ignored")  # whatever the orchestrator says
    ch._handler = handler

    update = _make_stub_update(text=None, photo=True)
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await ch._handle_media(update, context)

    # The handler may or may not be called (best-effort); we don't assert.
    # But the user MUST get a reply.
    update.message.reply_text.assert_awaited_once()
    sent = update.message.reply_text.await_args.args[0]
    assert isinstance(sent, str) and sent != "ignored"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_media_message_from_disallowed_chat_silently_dropped() -> None:
    ch = TelegramChannel("fake-token", allowed_chat_ids=[1])
    handler = AsyncMock()
    ch._handler = handler

    update = _make_stub_update(chat_id=999, text=None, photo=True)
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await ch._handle_media(update, context)

    handler.assert_not_called()
    update.message.reply_text.assert_not_called()
