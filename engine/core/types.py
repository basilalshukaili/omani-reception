"""Shared Pydantic v2 types for messages, turns, tools, and LLM responses."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    """Return a timezone-aware UTC ``datetime`` (default for created_at fields)."""
    return datetime.now(UTC)


class Role(StrEnum):
    """Conversational role of a turn or message author."""

    user = "user"
    assistant = "assistant"
    system = "system"
    tool = "tool"


class Attachment(BaseModel):
    """A non-text payload attached to a channel message (image, audio, file, etc.)."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"title": "Attachment"})

    kind: Literal["text", "image", "audio", "file"]
    url: str | None = None
    mime: str | None = None
    text: str | None = None


class ChannelMessage(BaseModel):
    """An inbound message from a channel adapter (Telegram, voice, etc.)."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"title": "ChannelMessage"})

    chat_id: str
    user_id: str | None = None
    text: str
    attachments: list[Attachment] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    received_at: datetime = Field(default_factory=_utcnow)


class ToolCall(BaseModel):
    """A tool invocation requested by the LLM."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"title": "ToolCall"})

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """The result of executing a tool call, fed back to the LLM."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"title": "ToolResult"})

    tool_call_id: str
    content: Any
    is_error: bool = False


class ToolSchema(BaseModel):
    """A tool definition exposed to the LLM (JSON Schema for input/output)."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"title": "ToolSchema"})

    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None


class Turn(BaseModel):
    """A single turn in the conversation transcript (user, assistant, system, or tool)."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"title": "Turn"})

    role: Role
    text: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)


class TokenUsage(BaseModel):
    """Token accounting returned by an LLM provider for a single call."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"title": "TokenUsage"})

    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int = 0


class LLMResponse(BaseModel):
    """Normalized response from any LLM adapter (Gemini/Claude/OpenAI)."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"title": "LLMResponse"})

    text: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: TokenUsage | None = None
    finish_reason: str | None = None
    raw: dict[str, Any] | None = None


__all__ = [
    "Attachment",
    "ChannelMessage",
    "LLMResponse",
    "Role",
    "TokenUsage",
    "ToolCall",
    "ToolResult",
    "ToolSchema",
    "Turn",
]
