"""Unit tests for ``engine.llm.normalize`` — tool-call schema round-trip.

We round-trip a canonical :class:`ToolSchema` through each provider's
outbound translator and verify:

1. The provider-native shape matches the documented contract.
2. A faux provider response built from that shape parses back into a
   canonical :class:`ToolCall` carrying the same name + arguments.

The "semantic equivalence" check is done by re-extracting just the
``name`` / ``description`` / ``parameters`` triple from each provider-native
form and comparing it to the input schema.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from engine.core.types import ToolCall, ToolSchema
from engine.llm.normalize import (
    parse_anthropic_tool_calls,
    parse_gemini_tool_calls,
    parse_openai_tool_calls,
    to_anthropic_tools,
    to_gemini_tools,
    to_openai_tools,
)

# ---------------------------------------------------------------------------
# Fixture: a sample tool the orchestrator might expose.
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_tool() -> ToolSchema:
    return ToolSchema(
        name="book_appointment",
        description="Book an appointment for the caller.",
        input_schema={
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "What service to book"},
                "when": {"type": "string", "description": "ISO date or natural language"},
            },
            "required": ["service", "when"],
        },
    )


@pytest.fixture
def sample_arguments() -> dict[str, Any]:
    return {"service": "haircut", "when": "tomorrow 10am"}


# ---------------------------------------------------------------------------
# Outbound: each translator produces the documented shape.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_to_gemini_tools_shape(sample_tool: ToolSchema) -> None:
    """Gemini packages everything under a single ``function_declarations`` list."""
    out = to_gemini_tools([sample_tool])

    assert isinstance(out, list)
    assert len(out) == 1
    assert "function_declarations" in out[0]
    decls = out[0]["function_declarations"]
    assert isinstance(decls, list)
    assert len(decls) == 1
    assert decls[0]["name"] == sample_tool.name
    assert decls[0]["description"] == sample_tool.description
    assert decls[0]["parameters"] == sample_tool.input_schema


@pytest.mark.unit
def test_to_anthropic_tools_shape(sample_tool: ToolSchema) -> None:
    """Anthropic uses a flat list of ``{name, description, input_schema}``."""
    out = to_anthropic_tools([sample_tool])

    assert isinstance(out, list)
    assert len(out) == 1
    assert out[0]["name"] == sample_tool.name
    assert out[0]["description"] == sample_tool.description
    assert out[0]["input_schema"] == sample_tool.input_schema


@pytest.mark.unit
def test_to_openai_tools_shape(sample_tool: ToolSchema) -> None:
    """OpenAI wraps each function in ``{"type": "function", "function": {...}}``."""
    out = to_openai_tools([sample_tool])

    assert isinstance(out, list)
    assert len(out) == 1
    assert out[0]["type"] == "function"
    fn = out[0]["function"]
    assert fn["name"] == sample_tool.name
    assert fn["description"] == sample_tool.description
    assert fn["parameters"] == sample_tool.input_schema


@pytest.mark.unit
def test_three_provider_outputs_are_semantically_equivalent(sample_tool: ToolSchema) -> None:
    """Re-project each provider's outbound shape back to a canonical triple."""
    g = to_gemini_tools([sample_tool])[0]["function_declarations"][0]
    a = to_anthropic_tools([sample_tool])[0]
    o = to_openai_tools([sample_tool])[0]["function"]

    triples = [
        (g["name"], g["description"], g["parameters"]),
        (a["name"], a["description"], a["input_schema"]),
        (o["name"], o["description"], o["parameters"]),
    ]
    # All three triples must match each other exactly.
    assert triples[0] == triples[1] == triples[2]


# ---------------------------------------------------------------------------
# Inbound: each parser recovers a canonical ToolCall.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_gemini_tool_call(sample_tool: ToolSchema, sample_arguments: dict[str, Any]) -> None:
    """A Gemini-shaped response with one function_call part -> one ToolCall."""
    gemini_resp = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "function_call": {
                                "name": sample_tool.name,
                                "args": sample_arguments,
                            }
                        }
                    ]
                }
            }
        ]
    }
    calls = parse_gemini_tool_calls(gemini_resp)

    assert len(calls) == 1
    assert isinstance(calls[0], ToolCall)
    assert calls[0].name == sample_tool.name
    assert calls[0].arguments == sample_arguments


@pytest.mark.unit
def test_parse_anthropic_tool_call(
    sample_tool: ToolSchema, sample_arguments: dict[str, Any]
) -> None:
    """An Anthropic-shaped response with a ``tool_use`` block -> one ToolCall."""
    anthropic_resp = {
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_01",
                "name": sample_tool.name,
                "input": sample_arguments,
            }
        ]
    }
    calls = parse_anthropic_tool_calls(anthropic_resp)

    assert len(calls) == 1
    assert calls[0].name == sample_tool.name
    assert calls[0].arguments == sample_arguments
    assert calls[0].id == "toolu_01"


@pytest.mark.unit
def test_parse_openai_tool_call(sample_tool: ToolSchema, sample_arguments: dict[str, Any]) -> None:
    """An OpenAI-shaped response with a tool_calls entry -> one ToolCall.

    OpenAI sends arguments as a JSON-encoded string; the parser must decode.
    """
    openai_resp = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_xyz",
                            "type": "function",
                            "function": {
                                "name": sample_tool.name,
                                "arguments": json.dumps(sample_arguments),
                            },
                        }
                    ],
                }
            }
        ]
    }
    calls = parse_openai_tool_calls(openai_resp)

    assert len(calls) == 1
    assert calls[0].name == sample_tool.name
    assert calls[0].arguments == sample_arguments
    assert calls[0].id == "call_xyz"


# ---------------------------------------------------------------------------
# Full round-trip — canonical -> provider-out -> faux provider response ->
# parsed canonical. The recovered tool-call must match the input semantically.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_full_round_trip_gemini(sample_tool: ToolSchema, sample_arguments: dict[str, Any]) -> None:
    """canonical -> to_gemini_tools -> faux response -> parse_gemini_tool_calls"""
    out = to_gemini_tools([sample_tool])
    fn_decl = out[0]["function_declarations"][0]

    # Build a faux response invoking the declared function.
    faux_resp = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "function_call": {
                                "name": fn_decl["name"],
                                "args": sample_arguments,
                            }
                        }
                    ]
                }
            }
        ]
    }
    calls = parse_gemini_tool_calls(faux_resp)

    assert len(calls) == 1
    assert calls[0].name == sample_tool.name
    assert calls[0].arguments == sample_arguments


@pytest.mark.unit
def test_full_round_trip_anthropic(
    sample_tool: ToolSchema, sample_arguments: dict[str, Any]
) -> None:
    out = to_anthropic_tools([sample_tool])
    decl = out[0]

    faux_resp = {
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_rt",
                "name": decl["name"],
                "input": sample_arguments,
            }
        ]
    }
    calls = parse_anthropic_tool_calls(faux_resp)

    assert len(calls) == 1
    assert calls[0].name == sample_tool.name
    assert calls[0].arguments == sample_arguments


@pytest.mark.unit
def test_full_round_trip_openai(sample_tool: ToolSchema, sample_arguments: dict[str, Any]) -> None:
    out = to_openai_tools([sample_tool])
    fn_decl = out[0]["function"]

    faux_resp = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_rt",
                            "type": "function",
                            "function": {
                                "name": fn_decl["name"],
                                "arguments": json.dumps(sample_arguments),
                            },
                        }
                    ],
                }
            }
        ]
    }
    calls = parse_openai_tool_calls(faux_resp)

    assert len(calls) == 1
    assert calls[0].name == sample_tool.name
    assert calls[0].arguments == sample_arguments


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_empty_tool_list_produces_empty_outputs() -> None:
    """No tools in -> Gemini's empty-bag wrapper / Anthropic+OpenAI empty lists."""
    assert to_anthropic_tools([]) == []
    assert to_openai_tools([]) == []
    g_out = to_gemini_tools([])
    # Gemini's wrapper always returns one envelope, but its inner list is empty.
    assert isinstance(g_out, list)
    assert len(g_out) == 1
    assert g_out[0].get("function_declarations") == []


@pytest.mark.unit
def test_parse_no_tool_calls_returns_empty() -> None:
    """A response with text-only content must yield no tool calls anywhere."""
    text_only_gemini = {"candidates": [{"content": {"parts": [{"text": "مرحبا"}]}}]}
    text_only_anthropic = {"content": [{"type": "text", "text": "مرحبا"}]}
    text_only_openai = {
        "choices": [{"message": {"role": "assistant", "content": "مرحبا", "tool_calls": None}}]
    }

    assert parse_gemini_tool_calls(text_only_gemini) == []
    assert parse_anthropic_tool_calls(text_only_anthropic) == []
    assert parse_openai_tool_calls(text_only_openai) == []


@pytest.mark.unit
def test_openai_parser_decodes_string_arguments() -> None:
    """OpenAI ships arguments as a JSON string — parser must decode (not pass through)."""
    resp = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": "x",
                            "type": "function",
                            "function": {
                                "name": "lookup",
                                "arguments": '{"id": 42}',
                            },
                        }
                    ]
                }
            }
        ]
    }
    calls = parse_openai_tool_calls(resp)
    assert calls[0].arguments == {"id": 42}
