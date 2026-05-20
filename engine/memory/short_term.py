"""Process-local conversation buffer for the P1 chat loop.

Stores recent turns per ``chat_id`` in a plain Python ``dict`` with a sliding
window. This is intentionally minimal — the real Redis-backed implementation
(plus rolling summarization) lands in P2. The public surface here is the same
one the Redis store will implement, so the orchestrator never changes.

Thread-safety: a single ``threading.Lock`` guards all mutations. We do not
need asyncio locks because the operations are all synchronous and short.
The orchestrator awaits I/O elsewhere; this module is pure memory.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import UTC, datetime

import structlog

from engine.core.session import ConversationSession
from engine.core.types import Turn

__all__ = ["InMemorySessionStore"]

log = structlog.get_logger(__name__)


class InMemorySessionStore:
    """Process-local conversation buffer. Replaced by Redis in P2.

    The store keeps a sliding window of the most recent ``max_turns`` turns
    per ``chat_id``. Older turns are dropped silently — no summarization
    happens here (that is a P2 concern handled by ``memory.summarizer``).
    """

    def __init__(self, max_turns: int = 12) -> None:
        """Initialize the store.

        Args:
            max_turns: Maximum number of turns retained per chat_id. When the
                buffer grows beyond this, the oldest turns are dropped first
                (FIFO sliding window).
        """
        if max_turns < 1:
            raise ValueError(f"max_turns must be >= 1, got {max_turns}")
        self._max_turns = max_turns
        self._sessions: dict[str, ConversationSession] = {}
        self._lock = threading.Lock()

    @property
    def max_turns(self) -> int:
        """The sliding-window cap configured at construction time."""
        return self._max_turns

    def get_or_create(self, chat_id: str, business_id: str) -> ConversationSession:
        """Return the session for ``chat_id``, creating it if absent.

        The returned object is the live session — mutations via :meth:`add_turn`
        are visible on subsequent reads.
        """
        with self._lock:
            session = self._sessions.get(chat_id)
            if session is None:
                session = ConversationSession(chat_id=chat_id, business_id=business_id)
                self._sessions[chat_id] = session
                log.debug(
                    "session.created",
                    chat_id=chat_id,
                    business_id=business_id,
                )
            return session

    def add_turn(self, chat_id: str, turn: Turn) -> None:
        """Append ``turn`` to the session and enforce the sliding window.

        Raises:
            KeyError: if no session exists for ``chat_id``. Callers must call
                :meth:`get_or_create` first.
        """
        with self._lock:
            session = self._sessions.get(chat_id)
            if session is None:
                raise KeyError(f"no session for chat_id={chat_id!r}; call get_or_create first")
            session.turns.append(turn)
            # Sliding window: drop oldest turns once we exceed the cap.
            overflow = len(session.turns) - self._max_turns
            if overflow > 0:
                # deque rotation is overkill; a slice assignment is clearer.
                del session.turns[:overflow]
            session.last_active_at = datetime.now(UTC)

    def recent_turns(self, chat_id: str, n: int | None = None) -> list[Turn]:
        """Return the most recent ``n`` turns (or all retained turns).

        Returns an empty list if no session exists for ``chat_id``. The
        returned list is a shallow copy — callers can mutate it freely.
        """
        with self._lock:
            session = self._sessions.get(chat_id)
            if session is None:
                return []
            if n is None or n >= len(session.turns):
                return list(session.turns)
            if n <= 0:
                return []
            # ``deque`` slicing is unavailable; use list slice on the live list.
            return list(session.turns[-n:])

    def reset(self, chat_id: str) -> None:
        """Drop all state for ``chat_id``. Used by ``/start`` to start fresh."""
        with self._lock:
            existed = self._sessions.pop(chat_id, None) is not None
        if existed:
            log.debug("session.reset", chat_id=chat_id)

    def all_chat_ids(self) -> list[str]:
        """Return every chat_id with a live session. For debugging / health checks."""
        with self._lock:
            return list(self._sessions.keys())

    def __len__(self) -> int:
        """Number of live sessions currently held in memory."""
        with self._lock:
            return len(self._sessions)


# Suppress unused-import warning: ``deque`` is kept available for the P2
# upgrade where bounded ring buffers become useful.
_ = deque
