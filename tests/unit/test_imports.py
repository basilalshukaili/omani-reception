"""Import-everything sanity test.

The cheapest possible canary: if any public engine module has a syntax error,
a missing import, or a circular dependency, one of these one-liner tests
fails with a clear ``ImportError`` instead of being masked behind a more
complex failure deeper in the suite.

Each module is imported in its own test function so a single failure points
straight at the broken module.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.unit
def test_import_engine() -> None:
    mod = importlib.import_module("engine")
    assert mod.__name__ == "engine"


@pytest.mark.unit
def test_import_engine_cli() -> None:
    mod = importlib.import_module("engine.cli")
    assert mod.__name__ == "engine.cli"


@pytest.mark.unit
def test_import_engine_config_schema() -> None:
    mod = importlib.import_module("engine.config.schema")
    assert mod.__name__ == "engine.config.schema"


@pytest.mark.unit
def test_import_engine_config_loader() -> None:
    mod = importlib.import_module("engine.config.loader")
    assert mod.__name__ == "engine.config.loader"


@pytest.mark.unit
def test_import_engine_core_types() -> None:
    mod = importlib.import_module("engine.core.types")
    assert mod.__name__ == "engine.core.types"


@pytest.mark.unit
def test_import_engine_core_session() -> None:
    mod = importlib.import_module("engine.core.session")
    assert mod.__name__ == "engine.core.session"


@pytest.mark.unit
def test_import_engine_observability_logging() -> None:
    mod = importlib.import_module("engine.observability.logging")
    assert mod.__name__ == "engine.observability.logging"
