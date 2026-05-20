"""Unit tests for ``engine.llm.factory.make_llm_provider``.

The factory is intentionally tiny — its job is to map a string (or the
``LLM_PROVIDER`` env var) to a concrete adapter without each call site having
to import every provider. Tests verify the routing matrix, env-var precedence,
and the ``require_api_key=False`` escape hatch used by adapter tests.
"""

from __future__ import annotations

import pytest

from engine.llm.base import LLMProvider, MissingAPIKey
from engine.llm.factory import make_llm_provider


@pytest.mark.unit
@pytest.mark.parametrize(
    "provider_name,expected_cls_name",
    [
        ("gemini", "GeminiProvider"),
        ("claude", "ClaudeProvider"),
        ("openai", "OpenAIProvider"),
    ],
)
def test_make_llm_provider_returns_correct_adapter(
    monkeypatch: pytest.MonkeyPatch, provider_name: str, expected_cls_name: str
) -> None:
    """Each provider literal must produce the right concrete class."""
    # Defensive: ensure no env override sneaks in.
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    p = make_llm_provider(provider_name, require_api_key=False)

    assert isinstance(p, LLMProvider)
    assert type(p).__name__ == expected_cls_name
    assert p.name == provider_name


@pytest.mark.unit
def test_unknown_provider_raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown literals must raise ``ValueError`` — no silent default."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    with pytest.raises(ValueError) as exc_info:
        make_llm_provider("ollama", require_api_key=False)

    assert "ollama" in str(exc_info.value)


@pytest.mark.unit
def test_default_is_gemini_when_no_arg_and_no_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No provider arg + no env var -> default to Gemini."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    p = make_llm_provider(None, require_api_key=False)

    assert p.name == "gemini"


@pytest.mark.unit
def test_env_var_overrides_default_when_arg_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``LLM_PROVIDER=claude`` beats the built-in default of gemini."""
    monkeypatch.setenv("LLM_PROVIDER", "claude")

    p = make_llm_provider(None, require_api_key=False)

    assert p.name == "claude"


@pytest.mark.unit
def test_explicit_arg_overrides_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit ``provider=`` arg wins over the env override."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    p = make_llm_provider("claude", require_api_key=False)

    assert p.name == "claude"


@pytest.mark.unit
def test_require_api_key_true_raises_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """``require_api_key=True`` + no key in env must raise ``MissingAPIKey`` eagerly.

    This is the "fail-fast in production" path the factory protects against:
    typoed env wiring should not silently produce a half-broken adapter.
    """
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    with pytest.raises(MissingAPIKey):
        make_llm_provider("gemini", require_api_key=True)


@pytest.mark.unit
@pytest.mark.parametrize(
    "provider_name,env_var",
    [
        ("gemini", "GEMINI_API_KEY"),
        ("claude", "ANTHROPIC_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
    ],
)
def test_require_api_key_true_succeeds_with_env_key(
    monkeypatch: pytest.MonkeyPatch, provider_name: str, env_var: str
) -> None:
    """When the env key is present, ``require_api_key=True`` must construct cleanly."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv(env_var, "dummy")

    p = make_llm_provider(provider_name, require_api_key=True)
    assert p.name == provider_name


@pytest.mark.unit
def test_model_arg_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """Caller-supplied model overrides the per-provider default model.

    We use ``require_api_key=False`` to keep the constructor side-effect-free,
    then poke the private ``_default_model`` attr (every adapter follows this
    naming convention per the brief).
    """
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    p = make_llm_provider("gemini", model="gemini-2.5-pro", require_api_key=False)
    assert getattr(p, "_default_model", None) == "gemini-2.5-pro"
