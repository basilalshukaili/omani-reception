"""Pydantic v2 schema for the per-business configuration contract.

Mirrors PLAN.md §10. Every section uses ``extra="forbid"`` so any typo in a
business YAML surfaces loudly at startup rather than silently coercing to a
default.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "BusinessConfig",
    "BusinessSection",
    "ChannelsSection",
    "ContactSection",
    "DialectSection",
    "EmbeddingSection",
    "HoursWindow",
    "LLMSection",
    "MemorySection",
    "ObservabilitySection",
    "PersonaSection",
    "RAGSection",
    "RateLimitSection",
    "ResponseStyle",
    "SecuritySection",
    "TelegramSection",
]

_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_VALID_DAYS = frozenset(
    {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
)


# ---------- business ----------


class ContactSection(BaseModel):
    """Optional contact details for the business."""

    model_config = ConfigDict(extra="forbid")

    phone: str | None = None
    email: str | None = None
    address: str | None = None


class HoursWindow(BaseModel):
    """A single open-close window within a day. Validated as ``HH:MM`` 24h."""

    model_config = ConfigDict(extra="forbid")

    open: str
    close: str

    @field_validator("open", "close")
    @classmethod
    def _validate_time(cls, value: str) -> str:
        if not _TIME_RE.match(value):
            raise ValueError(f"time must be HH:MM (24h), got: {value!r}")
        return value


class BusinessSection(BaseModel):
    """Top-level identity, contact, and hours for the business."""

    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    industry: str
    language: Literal["ar-OM"] = "ar-OM"
    timezone: str
    contact: ContactSection = Field(default_factory=ContactSection)
    hours: dict[str, list[HoursWindow]] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _validate_slug(cls, value: str) -> str:
        if not _SLUG_RE.match(value):
            raise ValueError(
                f"business.id must be snake_case slug matching {_SLUG_RE.pattern!r}, got: {value!r}"
            )
        return value

    @field_validator("hours")
    @classmethod
    def _validate_hours(cls, value: dict[str, list[HoursWindow]]) -> dict[str, list[HoursWindow]]:
        # Day names must be lowercase English weekday names. Empty list = closed.
        for day in value:
            if day != day.lower():
                raise ValueError(f"hours day key must be lowercase, got: {day!r}")
            if day not in _VALID_DAYS:
                raise ValueError(
                    f"hours day key must be one of {sorted(_VALID_DAYS)}, got: {day!r}"
                )
        return value


# ---------- persona ----------


class ResponseStyle(BaseModel):
    """Length-adaptation knobs for the receptionist persona."""

    model_config = ConfigDict(extra="forbid")

    length: Literal["adaptive", "fixed"] = "adaptive"
    max_words_casual: int = 40
    max_words_detailed: int = 150
    one_question_per_turn: bool = True


class PersonaSection(BaseModel):
    """The receptionist's identity, dialect region, and tone."""

    model_config = ConfigDict(extra="forbid")

    name: str
    role: str
    voice: str
    formality: Literal["low", "medium", "high"] = "high"
    region: Literal["muscat", "interior", "dhofari", "musandam"] = "muscat"
    address: Literal["plural_respect_default", "singular"] = "plural_respect_default"
    response_style: ResponseStyle = Field(default_factory=ResponseStyle)
    signature_close: str


# ---------- llm + embedding ----------


class LLMSection(BaseModel):
    """Primary chat-model provider and fallback wiring."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["gemini", "claude", "openai"] = "gemini"
    model: str
    temperature: float = Field(default=0.4, ge=0.0, le=1.0)
    max_tokens: int = 800
    fallback_provider: Literal["gemini", "claude", "openai"] | None = None
    fallback_model: str | None = None


class EmbeddingSection(BaseModel):
    """Embedding-model provider for RAG and long-term memory."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["gemini", "openai", "cohere"] = "gemini"
    model: str = "text-embedding-004"


# ---------- rag + dialect + memory ----------


class RAGSection(BaseModel):
    """Hybrid retrieval knobs (see PLAN.md §5)."""

    model_config = ConfigDict(extra="forbid")

    top_k: int = 5
    rerank: bool = False
    chunk_size_tokens: int = 400
    chunk_overlap_tokens: int = 60


class DialectSection(BaseModel):
    """Omani enforcement knobs (see PLAN.md §6)."""

    model_config = ConfigDict(extra="forbid")

    enforce: bool = True
    threshold: int = Field(default=70, ge=0, le=100)
    use_judge: bool = False
    max_corrections: int = 2
    banned_token_extras: list[str] = Field(default_factory=list)


class MemorySection(BaseModel):
    """Short-term buffer and long-term recall configuration."""

    model_config = ConfigDict(extra="forbid")

    short_term_turns: int = 12
    long_term_enabled: bool = True
    summarize_after_turns: int = 16


# ---------- channels ----------


class TelegramSection(BaseModel):
    """Telegram channel adapter configuration."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    allowed_chat_ids: list[int] = Field(default_factory=list)
    escalation_chat_id_env: str | None = None
    admin_chat_ids: list[int] = Field(default_factory=list)


class ChannelsSection(BaseModel):
    """All inbound/outbound channels for this business."""

    model_config = ConfigDict(extra="forbid")

    telegram: TelegramSection = Field(default_factory=TelegramSection)


# ---------- security + observability ----------


class RateLimitSection(BaseModel):
    """Per-chat and per-business token-bucket limits."""

    model_config = ConfigDict(extra="forbid")

    per_chat_burst: int = 5
    per_chat_sustained_per_min: int = 20
    per_business_daily_token_cap: int = 5_000_000


class SecuritySection(BaseModel):
    """Rate-limiting, language allow-list, and PII consent flag."""

    model_config = ConfigDict(extra="forbid")

    rate_limit: RateLimitSection = Field(default_factory=RateLimitSection)
    pii_consent: bool = False
    allow_languages: list[str] = Field(default_factory=lambda: ["ar"])


class ObservabilitySection(BaseModel):
    """Logging level and optional trace exporter."""

    model_config = ConfigDict(extra="forbid")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    trace_exporter: Literal["none", "otlp", "langfuse"] = "none"


# ---------- top-level ----------


class BusinessConfig(BaseModel):
    """Root contract for a single business. Loaded from ``config.yaml``."""

    model_config = ConfigDict(extra="forbid")

    business: BusinessSection
    persona: PersonaSection
    llm: LLMSection
    embedding: EmbeddingSection = Field(default_factory=lambda: EmbeddingSection())
    rag: RAGSection = Field(default_factory=RAGSection)
    dialect: DialectSection = Field(default_factory=DialectSection)
    memory: MemorySection = Field(default_factory=MemorySection)
    channels: ChannelsSection = Field(default_factory=ChannelsSection)
    security: SecuritySection = Field(default_factory=SecuritySection)
    observability: ObservabilitySection = Field(default_factory=ObservabilitySection)
