"""Unit tests for ``engine.prompts.system_builder.SystemPromptBuilder``.

Verifies the rendered Omani system prompt:

* Carries the persona name and business display_name verbatim
* Mentions every required lexicon entry (positive list)
* Mentions every banned form (so the model is told to avoid them)
* Renders business hours (at least one day name appears)
* Has no leftover Jinja syntax (template hygiene)

Test order matters less than coverage: each assertion catches one class of
template regression.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.config.loader import load_business_config
from engine.config.schema import BusinessConfig
from engine.prompts.system_builder import SystemPromptBuilder

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def generic_demo_config(repo_root: Path) -> BusinessConfig:
    return load_business_config("generic_demo", businesses_dir=repo_root / "businesses")


@pytest.fixture
def builder() -> SystemPromptBuilder:
    return SystemPromptBuilder()


@pytest.fixture
def rendered_prompt(builder: SystemPromptBuilder, generic_demo_config: BusinessConfig) -> str:
    return builder.build(generic_demo_config)


# ---------------------------------------------------------------------------
# Persona + business identity
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_prompt_contains_persona_name(
    rendered_prompt: str, generic_demo_config: BusinessConfig
) -> None:
    """Persona name (e.g., "سارة") must appear verbatim in the prompt."""
    assert generic_demo_config.persona.name in rendered_prompt
    assert "سارة" in rendered_prompt  # explicit sanity check on the demo config


@pytest.mark.unit
def test_prompt_contains_business_display_name(
    rendered_prompt: str, generic_demo_config: BusinessConfig
) -> None:
    """Business display name must surface so the persona can self-identify."""
    assert generic_demo_config.business.display_name in rendered_prompt
    assert "شركة الواحة للخدمات" in rendered_prompt


# ---------------------------------------------------------------------------
# Lexicon (must teach the right Omani)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "term",
    [
        "ويش",
        "ايوا",
        "كيف الحال",
        "كيف اقدر اخدم",  # service register — both "اخدمك"/"اخدمكم" forms pass
        "ما مشكلة",
        "لو سمحت",
    ],
)
def test_required_lexicon_entry_present(rendered_prompt: str, term: str) -> None:
    """Each canonical Omani term must be mentioned somewhere in the prompt."""
    assert term in rendered_prompt, f"missing required lexicon term: {term!r}"


# ---------------------------------------------------------------------------
# Banned forms (must be present in the "avoid" guidance)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "banned_term",
    [
        "شو",
        "إيش",
        "إيه",
        "شخبارك",
        "لو تكرم",
        "وايد",
        "ما في مشكلة",
    ],
)
def test_banned_form_mentioned(rendered_prompt: str, banned_term: str) -> None:
    """Each banned form must appear in the prompt so the model learns to avoid it.

    We don't try to enforce *where* it appears (some templates put them in a
    table, others in a bullet list) — only that they are mentioned.
    """
    assert banned_term in rendered_prompt, f"banned form not mentioned: {banned_term!r}"


# ---------------------------------------------------------------------------
# Hours rendering
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_hours_render_at_least_one_day(rendered_prompt: str) -> None:
    """The hours block should render at least one weekday by name.

    Day names may appear as English keys ("monday") or Arabic translations.
    The generic_demo config uses English keys, so we look for at least one.
    """
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    found = [day for day in weekdays if day in rendered_prompt]
    assert found, "no weekday names found in rendered prompt — hours block missing?"


@pytest.mark.unit
def test_hours_include_an_open_close_pair(rendered_prompt: str) -> None:
    """A specific open/close pair from the demo config should appear."""
    # generic_demo's weekday hours: 08:00-17:00
    assert "08:00" in rendered_prompt
    assert "17:00" in rendered_prompt


# ---------------------------------------------------------------------------
# Template hygiene — no leftover Jinja markers
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_unrendered_jinja_braces(rendered_prompt: str) -> None:
    """A leftover ``{{`` or ``{%`` means a template variable did not resolve."""
    assert "{{" not in rendered_prompt, "unrendered Jinja variable in prompt"
    assert "{%" not in rendered_prompt, "unrendered Jinja control block in prompt"


@pytest.mark.unit
def test_prompt_is_non_empty_arabic_string(rendered_prompt: str) -> None:
    """Sanity: rendered prompt should be a non-trivial Arabic string."""
    assert isinstance(rendered_prompt, str)
    assert len(rendered_prompt) > 200
    # Cheap "has Arabic" check — at least one Arabic letter in U+0621..U+064A.
    assert any("ء" <= ch <= "ي" for ch in rendered_prompt)


# ---------------------------------------------------------------------------
# Templates-dir wiring
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_missing_templates_dir_raises(tmp_path: Path) -> None:
    """Pointing at a non-existent dir must fail loudly at construction."""
    bad = tmp_path / "no_such_dir"
    with pytest.raises(FileNotFoundError):
        SystemPromptBuilder(templates_dir=bad)


@pytest.mark.unit
def test_default_templates_dir_is_used_when_none_passed(builder: SystemPromptBuilder) -> None:
    """Default ``templates_dir`` resolves to the bundled directory."""
    assert builder.templates_dir.is_dir()
    # Look for at least one .j2 file there.
    assert any(p.suffix == ".j2" for p in builder.templates_dir.iterdir())
