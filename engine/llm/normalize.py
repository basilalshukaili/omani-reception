"""Translate canonical :class:`ToolSchema` to/from each provider's tool-call format.

Each provider exposes function calling but with a slightly different shape:

* **Gemini** wraps a list of function declarations in ``[{"function_declarations": [...]}]``
  where each declaration has ``name``, ``description``, ``parameters`` (JSON
  Schema).
* **Anthropic** expects ``[{"name", "description", "input_schema"}]`` directly.
* **OpenAI** wraps each function in ``{"type": "function", "function": {...}}``.

This module also normalises tool-call **responses** back into a canonical
:class:`engine.core.types.ToolCall` list. The orchestrator only ever sees the
canonical form — adapter code translates on the boundary.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from engine.core.types import ToolCall, ToolSchema

# ---------------------------------------------------------------------------
# Outbound: canonical ToolSchema -> provider-native
# ---------------------------------------------------------------------------


def to_gemini_tools(tools: list[ToolSchema]) -> list[dict[str, Any]]:
    """Convert canonical tools into the single-element Gemini tool list.

    Gemini's ``tools`` parameter is a list, but typical usage is one element
    containing all function declarations together.
    """
    declarations = [
        {
            "name": t.name,
            "description": t.description,
            "parameters": t.input_schema,
        }
        for t in tools
    ]
    return [{"function_declarations": declarations}]


def to_anthropic_tools(tools: list[ToolSchema]) -> list[dict[str, Any]]:
    """Convert canonical tools into Anthropic's ``tools`` list."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in tools
    ]


def to_openai_tools(tools: list[ToolSchema]) -> list[dict[str, Any]]:
    """Convert canonical tools into OpenAI's chat-completion ``tools`` list."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]


# ---------------------------------------------------------------------------
# Inbound: provider-native response -> canonical ToolCall list
# ---------------------------------------------------------------------------


def parse_gemini_tool_calls(response: Any) -> list[ToolCall]:
    """Extract canonical :class:`ToolCall`s from a Gemini ``GenerateContentResponse``.

    Walks ``response.candidates[0].content.parts`` looking for ``function_call``
    parts. Gemini's API does not assign tool-call IDs, so we synthesise one.
    Accepts dict-shaped responses too (for tests that mock with plain dicts).
    """
    parts = _gemini_parts(response)
    calls: list[ToolCall] = []
    for part in parts:
        fc = _get(part, "function_call")
        if not fc:
            continue
        name = _get(fc, "name") or ""
        args = _get(fc, "args") or {}
        # Gemini's args is already a dict; defensively coerce JSON strings too.
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"_raw": args}
        calls.append(
            ToolCall(
                id=_get(fc, "id") or f"gemini-{uuid.uuid4().hex[:12]}",
                name=name,
                arguments=dict(args) if isinstance(args, dict) else {},
            )
        )
    return calls


def parse_anthropic_tool_calls(response: Any) -> list[ToolCall]:
    """Extract canonical :class:`ToolCall`s from an Anthropic ``Message`` response.

    Anthropic returns a list of content blocks; ``tool_use`` blocks carry the
    canonical ``id``, ``name``, ``input`` triple. Dict-shaped responses are
    accepted for test ergonomics.
    """
    content = _get(response, "content") or []
    calls: list[ToolCall] = []
    for block in content:
        if _get(block, "type") != "tool_use":
            continue
        calls.append(
            ToolCall(
                id=str(_get(block, "id") or f"anthropic-{uuid.uuid4().hex[:12]}"),
                name=str(_get(block, "name") or ""),
                arguments=dict(_get(block, "input") or {}),
            )
        )
    return calls


def parse_openai_tool_calls(response: Any) -> list[ToolCall]:
    """Extract canonical :class:`ToolCall`s from an OpenAI ``ChatCompletion``.

    Reads ``choices[0].message.tool_calls`` and parses the JSON ``arguments``
    string into a dict.
    """
    choices = _get(response, "choices") or []
    if not choices:
        return []
    message = _get(choices[0], "message")
    tool_calls_raw = _get(message, "tool_calls") or []
    calls: list[ToolCall] = []
    for tc in tool_calls_raw:
        function = _get(tc, "function")
        if function is None:
            continue
        name = _get(function, "name") or ""
        raw_args = _get(function, "arguments")
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                args = {"_raw": raw_args}
        elif isinstance(raw_args, dict):
            args = raw_args
        else:
            args = {}
        calls.append(
            ToolCall(
                id=str(_get(tc, "id") or f"openai-{uuid.uuid4().hex[:12]}"),
                name=str(name),
                arguments=args,
            )
        )
    return calls


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get(obj: Any, attr: str) -> Any:
    """Read ``attr`` from either an object (getattr) or a mapping (get).

    Keeps the parsers tolerant of mocked dict responses in tests while still
    working against real Pydantic SDK objects.
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(attr)
    return getattr(obj, attr, None)


def _gemini_parts(response: Any) -> list[Any]:
    """Return the parts of the first candidate of a Gemini response, or ``[]``."""
    candidates = _get(response, "candidates") or []
    if not candidates:
        return []
    content = _get(candidates[0], "content")
    parts = _get(content, "parts") or []
    return list(parts)


__all__ = [
    "parse_anthropic_tool_calls",
    "parse_gemini_tool_calls",
    "parse_openai_tool_calls",
    "to_anthropic_tools",
    "to_gemini_tools",
    "to_openai_tools",
]
