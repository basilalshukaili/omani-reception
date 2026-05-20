"""YAML loader for per-business config with env-var interpolation and strict validation.

Resolves ``${VAR}`` / ``${VAR:default}`` placeholders from ``os.environ`` while
walking the parsed YAML tree, then hands the dict to ``BusinessConfig`` for
Pydantic validation. Errors include the YAML file path so config bugs are
diagnosable from the log line alone.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

import structlog
import yaml
from pydantic import ValidationError

from engine.config.schema import BusinessConfig

__all__ = [
    "ConfigError",
    "export_json_schema",
    "find_repo_root",
    "load_business_config",
]

log = structlog.get_logger(__name__)

# Matches ${VAR} or ${VAR:default}. Defaults may contain anything except '}'.
_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}")


class ConfigError(RuntimeError):
    """Raised when a business config file is missing or fails validation."""


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from ``start`` (or cwd) looking for ``pyproject.toml``.

    Returns the first directory containing it. Raises ``ConfigError`` if no
    such directory is found before hitting the filesystem root.
    """
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise ConfigError(f"could not find repo root (no pyproject.toml above {here})")


def _interpolate_env(value: Any, *, path: str = "") -> Any:
    """Recursively replace ``${VAR}`` / ``${VAR:default}`` in strings."""
    if isinstance(value, str):
        return _ENV_VAR_PATTERN.sub(lambda m: _resolve_match(m, path), value)
    if isinstance(value, dict):
        return {k: _interpolate_env(v, path=f"{path}.{k}" if path else k) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env(item, path=f"{path}[{i}]") for i, item in enumerate(value)]
    return value


def _resolve_match(match: re.Match[str], path: str) -> str:
    var_name = match.group(1)
    default = match.group(2)
    if var_name in os.environ:
        return os.environ[var_name]
    if default is not None:
        return default
    # No default and var unset: emit a warning to stderr via structlog and
    # substitute empty string. Caller config will likely fail validation
    # downstream if the missing value was structurally required.
    print(
        f"warning: env var ${{{var_name}}} referenced at {path or '<root>'} is unset; "
        f"substituting empty string",
        file=sys.stderr,
    )
    log.warning(
        "config.env_var_missing",
        var=var_name,
        path=path or "<root>",
    )
    return ""


def load_business_config(
    business_id: str,
    *,
    businesses_dir: Path | None = None,
) -> BusinessConfig:
    """Load and validate ``<businesses_dir>/<business_id>/config.yaml``.

    Env-var interpolation runs before validation so secrets stay out of YAML.
    Missing files or validation errors raise ``ConfigError`` with the file path
    prefixed for fast diagnosis.
    """
    if businesses_dir is None:
        businesses_dir = find_repo_root() / "businesses"

    config_path = businesses_dir / business_id / "config.yaml"
    if not config_path.is_file():
        raise ConfigError(f"business config not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if not isinstance(raw, dict):
        raise ConfigError(
            f"{config_path}: top-level YAML must be a mapping, got {type(raw).__name__}"
        )

    interpolated = _interpolate_env(raw)

    try:
        return BusinessConfig.model_validate(interpolated)
    except ValidationError as exc:
        raise ConfigError(f"{config_path}: invalid config\n{exc}") from exc


def export_json_schema() -> dict[str, Any]:
    """Return the JSON Schema for ``BusinessConfig`` for editor/IDE tooling."""
    return BusinessConfig.model_json_schema()
