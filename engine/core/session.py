"""Conversation session skeleton — Redis-backed implementation lands in P2."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from engine.core.types import Turn


def _utcnow() -> datetime:
    """Return a timezone-aware UTC ``datetime``."""
    return datetime.now(UTC)


# TODO(P2): wire Redis backing for short-term turns + long-term summary
class ConversationSession(BaseModel):
    """In-memory conversation state for a single chat; persisted in Redis later."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"title": "ConversationSession"})

    chat_id: str
    business_id: str
    turns: list[Turn] = Field(default_factory=list)
    running_summary: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    last_active_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def add_turn(self, turn: Turn) -> None:
        """Append a turn to the transcript (real impl in P2)."""
        # P2 will write to Redis + update last_active_at + maybe trigger summarization.
        raise NotImplementedError("ConversationSession.add_turn lands in P2")

    def recent_turns(self, n: int) -> list[Turn]:
        """Return the most recent ``n`` turns (real impl in P2)."""
        raise NotImplementedError("ConversationSession.recent_turns lands in P2")

    def should_summarize(self, threshold: int) -> bool:
        """Return whether the transcript is long enough to warrant summarization."""
        # P2 will check len(turns) >= threshold; for the skeleton, always False.
        return False


__all__ = ["ConversationSession"]
