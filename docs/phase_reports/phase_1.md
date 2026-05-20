# Phase Report — P1: LLM Adapter & Chat Loop

- **Phase:** P1 — LLM Adapter & Chat Loop
- **Status:** ✅ Gate passed — live Omani greeting produced via Gemini 2.5-flash
- **Date:** 2026-05-20
- **Duration:** ~75 minutes (parallel sub-agents + integration + Gemini model bump)
- **Cost-to-date:** ~$0.001 (one smoke-test call)
- **Remaining build budget:** ~$4.999 of $5.00

## Live demo (the gate)

```
> python scripts/smoke_test_p1.py
BOT REPLY: وعليكم السلام ورحمة الله وبركاته، حياكم الله في شركة الواحة للخدمات،
           معاكم سارة موظفة الاستقبال. كيف اقدر اخدمكم؟

PASS: reply is non-empty, contains Arabic, came from live Gemini.
```

This single reply demonstrates:
- **Plural-of-respect** (حياكم) — the default address form per `dialect.region: muscat` config
- **Service-register opening** (كيف اقدر اخدمكم) — Basil's correction from planning, exact phrasing
- **Persona injection** (معاكم سارة) — `persona.name` flows through the prompt
- **Business identity** (شركة الواحة للخدمات) — `business.display_name` from config
- **Zero banned tokens** — no `شو`, `إيش`, `إيه`, `لو تكرم`, `وايد` (yaa-form), `ما في مشكلة`, MSA particles, foreign-dialect markers

## What was built

### LLM adapter layer (6 files + __init__)
- `engine/llm/base.py` — `LLMProvider` ABC, `Message`, `Pricing`, `LLMDelta`, `LLMProviderError`, `MissingAPIKey`
- `engine/llm/gemini.py` — live adapter via `google-genai`, lazy client construction, pricing table for 2.5-flash / 2.5-pro / 2.0-flash + `flash-latest`/`pro-latest` aliases
- `engine/llm/claude.py` — Anthropic SDK adapter, mocked-tested
- `engine/llm/openai.py` — OpenAI SDK adapter, mocked-tested
- `engine/llm/factory.py` — `make_llm_provider()` picks from config / `LLM_PROVIDER` env
- `engine/llm/normalize.py` — tool-call schema translation (canonical ↔ each provider's native shape)

### Channel layer (2 files)
- `engine/channels/base.py` — `Channel` ABC with `start(handler)`, `stop()`, `send(chat_id, content)`
- `engine/channels/telegram.py` — long-polling via `python-telegram-bot` v21: `/start`, `/teach` (admin-gated), plain text, media-rejection paths; allowed/admin chat-id allowlists; SIGINT/SIGTERM graceful shutdown

### Orchestrator + memory + prompts (4 files)
- `engine/core/orchestrator.py` — turn-by-turn loop; `/start` resets session and triggers greeting, `/teach` returns canned ack, attachment-only message returns canned text-only reply; response-length sanity warning (full corrector in P4)
- `engine/memory/short_term.py` — `InMemorySessionStore` (sliding window, thread-locked); Redis backing lands in P2
- `engine/prompts/system_builder.py` — Jinja2 renderer (StrictUndefined)
- `engine/prompts/templates/p1_system_prompt.j2` — Arabic system prompt with lexicon (use these / avoid these), persona, business identity + contact, hours, role boundaries (1,793 chars rendered for generic_demo)

### CLI + smoke test
- `engine/cli.py` — `chat` command implemented (live Telegram polling + `--no-telegram` stdin REPL fallback)
- `scripts/smoke_test_p1.py` — `/start` through orchestrator → live Gemini → validates Arabic output

### Tests (10 files, 146 new tests, 166 total passing in 9.46s)
- `tests/unit/test_llm_{base,gemini,claude,openai,factory,normalize}.py` — adapter contracts with mocked SDKs
- `tests/unit/test_orchestrator.py` — orchestrator with `FakeLLMProvider`, asserts lexicon presence in system prompt
- `tests/unit/test_short_term_session.py` — sliding window, multi-chat isolation
- `tests/unit/test_system_builder.py` — rendered prompt contains required Omani forms + banned forms (so the model is told what to avoid)
- `tests/unit/test_telegram_channel.py` — no-network construction, allowlist enforcement, media → ChannelMessage translation

### ADRs
- `docs/adrs/0002-llm-provider-abstraction.md`
- `docs/adrs/0006-channel-abstraction.md`

## Gate verification

| Check | Result | Evidence |
|---|---|---|
| `pytest -m unit` | ✅ pass | **166/166 passed in 9.46s** |
| `ruff check engine tests` | ✅ pass | All checks passed |
| `ruff format --check engine tests` | ✅ pass | 48 files already formatted |
| `mypy engine` | ✅ pass | Success: no issues found in 30 source files |
| `python -m engine.cli chat --help` | ✅ pass | Shows `--no-telegram` flag |
| Live Gemini smoke test | ✅ pass | Authentic Omani greeting produced (see above) |
| CI on PR #2 | ⏳ pending | Will validate on push |

## Decisions made during P1 (not in PLAN)

| Decision | Why |
|---|---|
| Default Gemini model changed from `gemini-1.5-flash` → **`gemini-2.5-flash`** | Live API returned 404 for 1.5 — Google has retired 1.5 family. 2.5-flash is the current free-tier-eligible cost-efficient model. Pricing table updated (2.5-flash: in $0.30/M, cached $0.075/M, out $2.50/M; 2.5-pro: in $1.25/M, out $10/M). |
| Orchestrator passes `list[Message]` (Pydantic, from `engine.llm.base`) instead of `list[dict]` | The local Protocol the orchestrator agent shipped diverged from the LLM-base ABC. Real adapters expect `Message` objects; tests use polymorphic helpers so they accept either. Aligning to `Message` avoids runtime errors with the live SDKs. |
| `keyword-only` markers (`*,`) added to the orchestrator's `LLMProvider` Protocol | Match the LLM-base ABC's signature exactly so mypy's structural check succeeds. |
| `disable_error_code = ["untyped-decorator"]` carried forward from P0 | click decorators still untyped at library level. |
| Added UTF-8 stdio reconfigure to `scripts/smoke_test_p1.py` | Windows cp1252 default kills `print()` of Arabic. Same idiom as `engine/cli.py`. |
| Added `gemini-flash-latest` / `gemini-pro-latest` aliases to the pricing table | Cover users who pin to the rolling stable channel. |

## Deferred / out of scope

| Item | Reason | When |
|---|---|---|
| Live Telegram polling round-trip | Requires the bot to be actively running while Basil sends `/start`. Setup is correct; user runs `python -m engine.cli chat` on his Docker PC. | When Basil runs the bot on PC2 |
| Full `docker compose up` | Docker Desktop not on this PC; P1 doesn't need it (in-memory session works). | P2 on Docker PC |
| Streaming responses | `stream()` is implemented in the LLM base but not yet wired into the orchestrator. | P2 or P4 (P4 may want streaming-aware corrector) |
| Cost ledger persistence to Postgres | Lives only as `estimate_cost_usd` helper now. | P6 (observability) |

## Open items for PC2 / P2

1. **Docker stack first boot.** Run `docker compose up -d` on the Docker PC. Verify `pg_isready` + `redis-cli ping` succeed before P2 work starts.
2. **Real session backing.** Replace `InMemorySessionStore` with `RedisSession` (same interface). P2 work.
3. **Add `tools_file` / `phrase_dir` / `examples_file` / `knowledge_dir` to BusinessConfig schema.** Surfaced in P0 phase report; consumed in P2 (ingest) and P3 (tools).
4. **Live Telegram test by Basil.** Run `python -m engine.cli chat --business generic_demo` and send `/start` to `@techmate_reception_bot` from his Telegram (chat_id 880315854). Verify the same greeting + start a real conversation.

## Cost summary

| Phase | Cost | Cumulative | Budget remaining |
|---|---|---|---|
| P0 | $0.00 | $0.00 | $5.00 |
| **P1** | **~$0.001** | **~$0.001** | **~$4.999** |

## What's next

**P2 — Memory & RAG.** Postgres+pgvector ingest, hybrid retrieval (BM25 + dense + RRF), Arabic normalization, Redis-backed session, long-term memory. **Requires Docker** — needs to happen on PC2 (or PC1 after Docker on D: drive install). HANDOFF.md is the bridge.
