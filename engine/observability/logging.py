"""Structured logging configuration for the reception engine."""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog


def _resolve_format(fmt: str) -> str:
    """Resolve ``fmt="auto"`` to either ``json`` or ``console`` based on env."""
    if fmt == "auto":
        env = os.environ.get("RECEPTION_ENV", "").strip().lower()
        return "json" if env == "prod" else "console"
    if fmt not in ("json", "console"):
        raise ValueError(f"Unsupported log format: {fmt!r} (expected 'auto'|'json'|'console')")
    return fmt


def configure_logging(level: str = "INFO", fmt: str = "auto") -> None:
    """Configure structlog + stdlib logging so all log lines share one pipeline."""
    resolved_fmt = _resolve_format(fmt)
    log_level = getattr(logging, level.upper(), logging.INFO)

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    # Shared processors run on BOTH structlog and stdlib log records so that
    # libraries (httpx, urllib3, asyncio, etc.) emit through the same pipeline.
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if resolved_fmt == "json":
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    # ---- structlog side ----
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # ---- stdlib side: route everything through structlog's formatter ----
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    # Replace existing handlers so repeated calls (e.g. across tests) don't stack.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(log_level)

    # Quiet a few notoriously chatty libraries unless explicitly debugging.
    if log_level > logging.DEBUG:
        for noisy in ("httpx", "httpcore", "urllib3", "asyncio"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger; pass ``name`` to scope it (e.g. ``__name__``)."""
    return structlog.stdlib.get_logger(name) if name else structlog.stdlib.get_logger()
