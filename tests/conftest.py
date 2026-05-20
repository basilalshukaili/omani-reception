"""Shared pytest fixtures for the Omani Receptionist test suite.

Anything in this file is auto-discovered by pytest for every test under
``tests/``. Keep it lean — fixtures here should be genuinely reusable across
unit, integration, dialect, and e2e suites. Heavy or domain-specific fixtures
belong in a closer ``conftest.py`` (e.g. ``tests/integration/conftest.py``).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

# ---------- repo + filesystem ----------


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Absolute path to the repo root (the directory containing ``pyproject.toml``).

    Walks up from this conftest file until a ``pyproject.toml`` is found. We
    avoid relying on ``Path.cwd()`` because pytest may be invoked from anywhere.
    """
    here = Path(__file__).resolve().parent
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError(f"could not locate repo root (no pyproject.toml at or above {here})")


@pytest.fixture
def tmp_business_dir(tmp_path: Path) -> Path:
    """Create a tmp ``businesses/test_biz/`` skeleton and return its path.

    The layout mirrors what real businesses live at — ``knowledge/``,
    ``phrases/``, ``examples/`` — so loader/RAG code that walks the directory
    sees a realistic shape.
    """
    business_dir = tmp_path / "businesses" / "test_biz"
    business_dir.mkdir(parents=True)
    (business_dir / "knowledge").mkdir()
    (business_dir / "phrases").mkdir()
    (business_dir / "examples").mkdir()
    return business_dir


# ---------- config YAML fixtures ----------


_MIN_VALID_YAML = textwrap.dedent(
    """\
    business:
      id: test_biz
      display_name: "اختبار"
      industry: general_services
      language: ar-OM
      timezone: Asia/Muscat

    persona:
      name: "سارة"
      role: "موظفة استقبال"
      voice: "محترمة، رسمية"
      formality: high
      region: muscat
      address: plural_respect_default
      signature_close: "تحت أمركم"

    llm:
      provider: gemini
      model: gemini-2.5-flash
    """
)


# A config that fails validation because ``persona.formality`` is not one of
# the literals {low, medium, high}. Useful for negative-path tests without
# needing to construct a Pydantic model by hand.
_INVALID_YAML = textwrap.dedent(
    """\
    business:
      id: test_biz
      display_name: "اختبار"
      industry: general_services
      language: ar-OM
      timezone: Asia/Muscat

    persona:
      name: "سارة"
      role: "موظفة استقبال"
      voice: "محترمة"
      formality: casual           # invalid: not one of {low, medium, high}
      region: muscat
      address: plural_respect_default
      signature_close: "تحت أمركم"

    llm:
      provider: gemini
      model: gemini-2.5-flash
    """
)


@pytest.fixture
def valid_config_yaml(tmp_business_dir: Path) -> Path:
    """Write a minimal-but-valid ``config.yaml`` into ``tmp_business_dir``."""
    cfg = tmp_business_dir / "config.yaml"
    cfg.write_text(_MIN_VALID_YAML, encoding="utf-8")
    return cfg


@pytest.fixture
def invalid_config_yaml(tmp_business_dir: Path) -> Path:
    """Write a ``config.yaml`` that should fail Pydantic validation."""
    cfg = tmp_business_dir / "config.yaml"
    cfg.write_text(_INVALID_YAML, encoding="utf-8")
    return cfg


# ---------- utility helpers (not fixtures) ----------


def set_env(monkeypatch: pytest.MonkeyPatch, **kwargs: str) -> None:
    """Set several environment variables at once via ``monkeypatch``.

    This is a plain helper, intentionally not decorated with ``@pytest.fixture``
    — call it inside a test that already has ``monkeypatch`` injected.

    Example::

        def test_thing(monkeypatch):
            set_env(monkeypatch, TELEGRAM_BOT_TOKEN="x", FOO="bar")
    """
    for key, value in kwargs.items():
        monkeypatch.setenv(key, value)
