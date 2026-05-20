"""Click-based CLI for the Omani Arabic AI Receptionist engine."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import os
import sys
from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    from engine.core.orchestrator import Orchestrator


def _ensure_utf8_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8 so Arabic output never crashes on Windows."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            # Stream may already be closed or not reconfigurable; ignore.
            with contextlib.suppress(ValueError, OSError):
                reconfigure(encoding="utf-8", errors="replace")


# stdio MUST be reconfigured before structlog imports — Arabic console output
# on Windows depends on it. The E402 violations below are intentional.
_ensure_utf8_stdio()

from engine import __version__  # noqa: E402
from engine.observability.logging import configure_logging, get_logger  # noqa: E402

DEFAULT_BUSINESS_ID = "generic_demo"
_BUSINESS_ENV = "RECEPTION_BUSINESS_ID"


def _default_business() -> str:
    """Pick the default business id from env, falling back to ``generic_demo``."""
    return os.environ.get(_BUSINESS_ENV, DEFAULT_BUSINESS_ID)


def _business_option() -> Any:
    """Shared ``--business`` option used by every sub-command."""
    return click.option(
        "--business",
        "business_id",
        default=_default_business,
        show_default=DEFAULT_BUSINESS_ID,
        help="Business id (defaults to $RECEPTION_BUSINESS_ID or 'generic_demo').",
    )


def _log_level_option() -> Any:
    """Shared ``--log-level`` option used by every sub-command."""
    return click.option(
        "--log-level",
        default="INFO",
        show_default=True,
        type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], case_sensitive=False),
        help="Logging verbosity for this invocation.",
    )


def _load_business_config(business_id: str) -> Any:
    """Best-effort loader: tries common entry points exposed by ``engine.config``.

    The config layer is owned by another agent — this helper stays resilient to
    whichever public name they expose (``load_business_config`` / ``load_config`` /
    ``BusinessConfig.load`` / ``load``). Probes the package, then ``engine.config.loader``.
    """
    candidate_modules: list[Any] = []
    for mod_name in ("engine.config", "engine.config.loader"):
        try:
            candidate_modules.append(importlib.import_module(mod_name))
        except ImportError:
            continue

    for mod in candidate_modules:
        for attr in ("load_business_config", "load_config", "load"):
            loader = getattr(mod, attr, None)
            if callable(loader):
                return loader(business_id)
        cls = getattr(mod, "BusinessConfig", None)
        if cls is not None and hasattr(cls, "load"):
            return cls.load(business_id)

    raise RuntimeError(
        "engine.config does not expose a known loader "
        "(expected one of: load_business_config, load_config, load, BusinessConfig.load)"
    )


def _safe_get(obj: Any, *path: str, default: Any = "<unknown>") -> Any:
    """Walk a dotted attribute / key path on a pydantic model or dict."""
    cur: Any = obj
    for part in path:
        if cur is None:
            return default
        cur = cur.get(part, default) if isinstance(cur, dict) else getattr(cur, part, default)
        if cur is default:
            return default
    return cur


async def _stdin_repl(orchestrator: Orchestrator, business_id: str) -> None:
    """Tiny local REPL for testing without Telegram.

    Sends a ``/start`` automatically, prints the bot reply, then reads stdin
    line-by-line. Blank line exits. Used by ``chat --no-telegram``.
    """
    from datetime import UTC, datetime

    from engine.core.types import ChannelMessage

    chat_id = "_repl"

    # Send a /start automatically so the user sees the greeting first.
    start_msg = ChannelMessage(
        chat_id=chat_id,
        user_id=chat_id,
        text="/start",
        received_at=datetime.now(UTC),
        metadata={"command": "start"},
    )
    reply = await orchestrator.handle(start_msg)
    click.echo(f"BOT: {reply}\n")

    click.echo(f"(business='{business_id}' — type a message, blank line to exit)")
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, input, "YOU: ")
        if not line.strip():
            break
        msg = ChannelMessage(
            chat_id=chat_id,
            user_id=chat_id,
            text=line,
            received_at=datetime.now(UTC),
            metadata={},
        )
        reply = await orchestrator.handle(msg)
        click.echo(f"BOT: {reply}\n")


@click.group(
    name="cli",
    help="Reception — Omani Arabic AI Receptionist engine.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(version=__version__, prog_name="reception")
def cli() -> None:
    """Top-level command group for the reception engine."""


@cli.command(help="Validate config + report health for a business.")
@_business_option()
@_log_level_option()
def health(business_id: str, log_level: str) -> None:
    """Load the business config and print a structured health report."""
    configure_logging(level=log_level)
    log = get_logger("engine.cli.health")
    log.info("health.start", business_id=business_id)

    try:
        config = _load_business_config(business_id)
    except FileNotFoundError as e:
        log.error("health.config_missing", business_id=business_id, error=str(e))
        click.echo(f"ERROR: config not found for business '{business_id}': {e}", err=True)
        sys.exit(1)
    except (ImportError, ModuleNotFoundError) as e:
        log.error("health.config_import_error", business_id=business_id, error=str(e))
        click.echo(f"ERROR: cannot import engine.config: {e}", err=True)
        sys.exit(1)
    except (ValueError, TypeError, RuntimeError) as e:
        log.error("health.config_invalid", business_id=business_id, error=str(e))
        click.echo(f"ERROR: invalid config for business '{business_id}': {e}", err=True)
        sys.exit(1)
    except Exception as e:
        log.exception("health.config_unexpected", business_id=business_id)
        click.echo(f"ERROR: unexpected failure loading config: {e}", err=True)
        sys.exit(1)

    report = {
        "business_id": _safe_get(config, "business", "id", default=business_id),
        "persona_name": _safe_get(config, "persona", "name"),
        "llm_provider": _safe_get(config, "llm", "provider"),
        "llm_model": _safe_get(config, "llm", "model"),
        "dialect_region": _safe_get(config, "persona", "region"),
        "dialect_enforce": _safe_get(config, "dialect", "enforce"),
    }

    click.echo("reception health: OK")
    click.echo(f"  business_id     : {report['business_id']}")
    click.echo(f"  persona_name    : {report['persona_name']}")
    click.echo(f"  llm_provider    : {report['llm_provider']}")
    click.echo(f"  llm_model       : {report['llm_model']}")
    click.echo(f"  dialect_region  : {report['dialect_region']}")
    click.echo(f"  dialect_enforce : {report['dialect_enforce']}")

    log.info("health.ok", **report)


@cli.command(help="Run the Telegram chat loop (LIVE — connects to Telegram + Gemini).")
@_business_option()
@_log_level_option()
@click.option(
    "--no-telegram",
    is_flag=True,
    default=False,
    help="Run the orchestrator in a local stdin REPL instead of connecting to Telegram.",
)
def chat(business_id: str, log_level: str, no_telegram: bool) -> None:
    """Start the receptionist bot.

    By default connects to Telegram via long-polling. Use ``--no-telegram`` for a
    local REPL (useful when you want to test the LLM/orchestrator without a
    Telegram round-trip).
    """
    configure_logging(level=log_level)
    log = get_logger("engine.cli.chat")

    # Late imports — these modules pull in third-party SDKs (google-genai,
    # python-telegram-bot, …) that we don't want to import unless ``chat``
    # actually runs. They also exist on disk only when concurrent agents have
    # landed their work, so importing at module scope would break ``--help``
    # for the other subcommands while P1 is in flight.
    from engine.channels.telegram import TelegramChannel
    from engine.core.orchestrator import Orchestrator
    from engine.core.types import ChannelMessage
    from engine.llm.factory import make_llm_provider
    from engine.memory.short_term import InMemorySessionStore
    from engine.prompts.system_builder import SystemPromptBuilder

    # 1. Load config
    config = _load_business_config(business_id)

    # 2. Build dependencies
    llm = make_llm_provider(
        provider=config.llm.provider,
        model=config.llm.model,
    )
    session_store = InMemorySessionStore(max_turns=config.memory.short_term_turns)
    system_builder = SystemPromptBuilder()
    orchestrator = Orchestrator(
        config=config,
        llm=llm,
        session_store=session_store,
        system_builder=system_builder,
    )

    if no_telegram:
        asyncio.run(_stdin_repl(orchestrator, business_id))
        return

    # 3. Wire Telegram channel
    token = os.environ.get(config.channels.telegram.bot_token_env, "")
    if not token:
        click.echo(
            f"ERROR: {config.channels.telegram.bot_token_env} not set in env. "
            f"Add it to .env or run with --no-telegram.",
            err=True,
        )
        sys.exit(1)

    allowed = set(config.channels.telegram.allowed_chat_ids) or None
    admin = set(config.channels.telegram.admin_chat_ids) or None
    channel = TelegramChannel(
        token=token,
        allowed_chat_ids=allowed,
        admin_chat_ids=admin,
    )

    async def handler(msg: ChannelMessage) -> str:
        return await orchestrator.handle(msg)

    log.info(
        "chat.starting",
        business_id=business_id,
        provider=config.llm.provider,
        model=config.llm.model,
    )
    click.echo(f"Bot starting for business='{business_id}' via Telegram. Ctrl-C to stop.")

    try:
        asyncio.run(channel.start(handler))
    except KeyboardInterrupt:
        log.info("chat.stopped_by_user")
        click.echo("Bot stopped.")


@cli.command(help="Ingest knowledge files into the RAG store (lands in P2).")
@_business_option()
@_log_level_option()
def ingest(business_id: str, log_level: str) -> None:
    """Stub for the knowledge ingestor — real implementation in P2."""
    configure_logging(level=log_level)
    log = get_logger("engine.cli.ingest")
    log.info("ingest.stub", business_id=business_id)
    click.echo("ingest coming in P2")


@cli.command(name="eval", help="Run the dialect/golden eval suite (lands in P4).")
@_business_option()
@_log_level_option()
def eval_cmd(business_id: str, log_level: str) -> None:
    """Stub for the eval runner — real implementation in P4."""
    configure_logging(level=log_level)
    log = get_logger("engine.cli.eval")
    log.info("eval.stub", business_id=business_id)
    click.echo("eval coming in P4")


# Entry point alias used by ``[project.scripts] reception = "engine.cli:main"``.
main = cli


if __name__ == "__main__":
    cli()
