"""Unit tests for ``engine.config.loader`` and ``engine.config.schema``.

These tests cover the happy-path load of the shipped ``generic_demo`` config,
several Pydantic validation failures, env-var interpolation, and the
"business not found" error path. They are isolated from the filesystem outside
of ``tmp_path`` and never hit the network.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from engine.config.loader import ConfigError, load_business_config
from engine.config.schema import BusinessConfig

# ---------- happy path ----------


@pytest.mark.unit
def test_generic_demo_config_loads_and_parses(repo_root: Path) -> None:
    """The shipped ``businesses/generic_demo/config.yaml`` must load cleanly.

    This doubles as a regression test: if anyone breaks the schema or the demo
    config, this fails on CI before P1 even starts.
    """
    cfg = load_business_config("generic_demo", businesses_dir=repo_root / "businesses")

    assert isinstance(cfg, BusinessConfig)
    assert cfg.business.id == "generic_demo"
    assert cfg.persona.region == "muscat"
    assert cfg.llm.provider == "gemini"
    assert cfg.dialect.enforce is True


# ---------- invalid configs ----------


@pytest.mark.unit
def test_invalid_config_raises(invalid_config_yaml: Path) -> None:
    """A config with an out-of-literal value must fail validation.

    The loader wraps ``pydantic.ValidationError`` in ``ConfigError`` with the
    file path included. We accept either type to stay tolerant if that wrapping
    behaviour changes.
    """
    # ``invalid_config_yaml`` lives at <tmp>/businesses/test_biz/config.yaml.
    businesses_dir = invalid_config_yaml.parent.parent

    with pytest.raises((ConfigError, ValueError)) as exc_info:
        load_business_config("test_biz", businesses_dir=businesses_dir)

    # The bad value should appear in the error chain somewhere.
    assert "casual" in str(exc_info.value) or "formality" in str(exc_info.value)


@pytest.mark.unit
def test_missing_business_raises(tmp_path: Path) -> None:
    """Pointing at a non-existent business slug must raise, not silently default."""
    empty_businesses = tmp_path / "businesses"
    empty_businesses.mkdir()

    # Tolerant: implementations may use ConfigError, FileNotFoundError, or OSError.
    with pytest.raises((ConfigError, FileNotFoundError, OSError)):
        load_business_config("does_not_exist", businesses_dir=empty_businesses)


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad_id",
    [
        "Bad-ID-With-Caps",  # uppercase + hyphens
        "1starts_with_digit",  # leading digit
        "has spaces",  # whitespace
        "with-dash",  # hyphen not allowed
        "",  # empty
    ],
)
def test_business_id_slug_enforced(tmp_business_dir: Path, bad_id: str) -> None:
    """``business.id`` must be a snake_case slug; everything else is rejected."""
    cfg_text = textwrap.dedent(
        f"""\
        business:
          id: "{bad_id}"
          display_name: "x"
          industry: general_services
          language: ar-OM
          timezone: Asia/Muscat

        persona:
          name: "س"
          role: "ر"
          voice: "v"
          formality: high
          region: muscat
          address: plural_respect_default
          signature_close: "c"

        llm:
          provider: gemini
          model: gemini-2.5-flash
        """
    )
    (tmp_business_dir / "config.yaml").write_text(cfg_text, encoding="utf-8")

    with pytest.raises((ConfigError, ValueError)):
        load_business_config("test_biz", businesses_dir=tmp_business_dir.parent)


# ---------- env-var interpolation ----------


@pytest.mark.unit
def test_env_var_interpolation_resolves(
    tmp_business_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``${VAR}`` placeholders inside YAML values must be substituted from env."""
    monkeypatch.setenv("TEST_VAR", "my-real-token")

    cfg_text = textwrap.dedent(
        """\
        business:
          id: test_biz
          display_name: "x"
          industry: general_services
          language: ar-OM
          timezone: Asia/Muscat

        persona:
          name: "س"
          role: "ر"
          voice: "v"
          formality: high
          region: muscat
          address: plural_respect_default
          signature_close: "c"

        llm:
          provider: gemini
          model: gemini-2.5-flash

        channels:
          telegram:
            enabled: true
            bot_token_env: "${TEST_VAR}"
        """
    )
    (tmp_business_dir / "config.yaml").write_text(cfg_text, encoding="utf-8")

    cfg = load_business_config("test_biz", businesses_dir=tmp_business_dir.parent)

    assert cfg.channels.telegram.bot_token_env == "my-real-token"
