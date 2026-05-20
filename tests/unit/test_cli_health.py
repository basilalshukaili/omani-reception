"""Smoke tests for the ``reception`` CLI entry point.

These are deliberately thin — we're not testing CLI logic in detail here,
just confirming that the entry point boots, accepts the expected flags, and
exits with sensible codes. Deeper CLI behaviour will be covered once the
``chat`` / ``ingest`` / ``eval`` subcommands have real implementations.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from engine.cli import main as cli_main


@pytest.mark.unit
def test_health_ok_for_generic_demo() -> None:
    """``reception health`` should exit 0 when the default business validates."""
    runner = CliRunner()
    result = runner.invoke(cli_main, ["health"])
    # Print captured output to help diagnose on failure (pytest -s users will
    # see it). We rely on ``result.output`` capture rather than real stdout.
    assert result.exit_code == 0, result.output


@pytest.mark.unit
def test_health_fails_for_unknown_business() -> None:
    """An unknown business slug must produce a non-zero exit and not crash silently."""
    runner = CliRunner()
    result = runner.invoke(cli_main, ["health", "--business", "does_not_exist"])
    assert result.exit_code != 0


@pytest.mark.unit
def test_help_lists_health_subcommand() -> None:
    """``reception --help`` must advertise the health subcommand."""
    runner = CliRunner()
    result = runner.invoke(cli_main, ["--help"])
    assert result.exit_code == 0
    assert "health" in result.output


@pytest.mark.unit
def test_version_flag_shows_package_version() -> None:
    """``--version`` should print the engine's semantic version."""
    runner = CliRunner()
    result = runner.invoke(cli_main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output
