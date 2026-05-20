"""P1 smoke test: simulate a /start through the orchestrator with the live Gemini API.

Run with the GEMINI_API_KEY set in env (or in .env). Exits 0 on success.
Cost: ~0.001 USD per run (Gemini Flash, small prompt + small response).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

# Windows cp1252 default kills Arabic print(); reconfigure to UTF-8 before anything else.
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        with contextlib.suppress(ValueError, OSError):
            _reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

# Make ``engine`` importable when the script is invoked as
# ``python scripts/smoke_test_p1.py`` (Python adds ``scripts/`` to sys.path, not
# the repo root). Editable installs (``pip install -e .``) make this redundant
# but harmless.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Load .env from repo root if present, before any engine imports that may read env.
_env_path = _REPO_ROOT / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

from engine.config.loader import load_business_config  # noqa: E402
from engine.core.orchestrator import Orchestrator  # noqa: E402
from engine.core.types import ChannelMessage  # noqa: E402
from engine.llm.factory import make_llm_provider  # noqa: E402
from engine.memory.short_term import InMemorySessionStore  # noqa: E402
from engine.observability.logging import configure_logging, get_logger  # noqa: E402
from engine.prompts.system_builder import SystemPromptBuilder  # noqa: E402

# Arabic Unicode block (U+0600 — U+06FF). Used to verify the reply is Arabic.
ARABIC_RANGE = re.compile(r"[؀-ۿ]")


async def main() -> int:
    """Run one /start through the orchestrator and assert the reply is Arabic."""
    configure_logging(level="INFO", fmt="console")
    log = get_logger("smoke_test_p1")

    if not os.environ.get("GEMINI_API_KEY"):
        log.error("smoke.no_api_key", env_var="GEMINI_API_KEY")
        print(
            "ERROR: GEMINI_API_KEY not set. Add it to .env at the repo root.",
            file=sys.stderr,
        )
        return 1

    config = load_business_config("generic_demo")
    llm = make_llm_provider(provider=config.llm.provider, model=config.llm.model)
    session = InMemorySessionStore(max_turns=config.memory.short_term_turns)
    builder = SystemPromptBuilder()
    orch = Orchestrator(
        config=config,
        llm=llm,
        session_store=session,
        system_builder=builder,
    )

    msg = ChannelMessage(
        chat_id="smoke_test",
        user_id="smoke_test",
        text="/start",
        attachments=[],
        metadata={"command": "start"},
        received_at=datetime.now(UTC),
    )

    log.info("smoke.sending", text=msg.text, chat_id=msg.chat_id)
    reply = await orch.handle(msg)
    log.info("smoke.received", reply_len=len(reply), reply_preview=reply[:80])

    print("\n=== Smoke Test Result ===")
    print(f"BOT REPLY: {reply}")
    print()

    if not reply.strip():
        print("FAIL: empty reply", file=sys.stderr)
        return 1

    arabic_chars = len(ARABIC_RANGE.findall(reply))
    if arabic_chars < 5:
        print(
            f"FAIL: reply has only {arabic_chars} Arabic characters — expected mostly Arabic",
            file=sys.stderr,
        )
        return 1

    # Sanity checks against the banned tokens (advisory — not a hard failure).
    banned = [
        "شو",
        "إيش",
        "إيه",
        "لو تكرم",
        "وايد",
        "شلون",
        "إزاي",
        "عايز",
        "ماذا",
        "أين",
    ]
    found_banned = [b for b in banned if b in reply]
    if found_banned:
        print(
            f"WARN: banned tokens found in reply: {found_banned}",
            file=sys.stderr,
        )
        print(
            "      (not a hard failure — sometimes the model slips; will be tightened in P4)",
            file=sys.stderr,
        )

    print("PASS: reply is non-empty, contains Arabic, came from live Gemini.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
