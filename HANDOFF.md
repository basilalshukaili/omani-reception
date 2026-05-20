# HANDOFF — For a fresh Claude Code session resuming this project

> **Read this file first.** It tells you the current state, the user's preferences, and the next concrete step. Everything else in the repo (PLAN.md, ADRs, phase reports, code) is reachable from here.

## What this project is

An **Omani Arabic AI Receptionist** — chat-only over Telegram, conversing in authentic **Muscat / coastal (Sahili) Omani Khaleeji** in an **official-respectful** register. Built as a **general scaffold**: a new business is onboarded by editing `businesses/<name>/config.yaml` + dropping a folder of knowledge/phrases — **zero engine code changes per business**.

Repo: **https://github.com/basilalshukaili/omani-reception** (public)

## Who the user is

- **Basil Al-Shukaili** (GitHub: `basilalshukaili`, Telegram: `@BasiI`, chat_id `880315854`)
- **Native Omani Khaleeji speaker** — his dialect verdicts are authoritative. When he corrects a phrase, that's the source of truth. Update the lexicon, banned-tokens, and phrase library accordingly; do not argue or restore.
- Wants **quality first**, hates flooding short conversations with long replies.
- Working with a friend on this repo via feature-branch + PR flow, non-concurrent.

## The hard constraints (do not violate)

1. **Cost cap: $5 USD total** for the entire build. Gemini's free tier covers most. Track every paid call in `engine/observability/cost_tracker.py` (lands in P6). Warn at $3, hard-stop at $5.
2. **Gemini is the only live LLM provider for v1.** Claude/OpenAI adapters are written and unit-tested with mocked HTTP, but no live key is required. Default model: `gemini-2.5-flash` for normal turns, `gemini-2.5-pro` for evaluation/judge calls.
3. **Embeddings: Google `text-embedding-004`** (free in Gemini tier). Adapters for OpenAI/Cohere preserved but not exercised live.
4. **Region: Muscat / coastal Sahili Omani only.** Don't mix regions (don't slip in Dhofari/interior/Musandam phrasings). Per-business override is available via `dialect.region` but `generic_demo` is Muscat.
5. **Register: official-respectful.** Plural-of-respect (`حياكم`, `تفضلوا`, `كيف اقدر اخدمكم`) is the default address form. No street slang. No casual filler. Receptionist speaks like a polite professional, not a friend at a majlis.
6. **Response length: adaptive.** A short message gets a short reply. Default to brevity. Soft cap 40 words for casual turns, hard cap 150 for detailed answers. One question per reply maximum.
7. **No live customer rollout without a native-speaker review pass** of the phrase library and a 50-turn sample. Documented in PLAN.md §6.6.

## Lexicon (authoritative — sync with `PLAN.md` §6.3 on `main`)

> **The lexicon in `PLAN.md` is the source of truth.** Re-read it before generating any Omani phrasing. The list below is a quick reference; if it disagrees with PLAN.md, **PLAN wins**.

| MSA / English | Use (Omani) | Reject (banned-tokens) |
|---|---|---|
| ماذا / "what" | **ويش** | شو, إيش |
| نعم / "yes" | **ايوا** | إيه, هاء |
| "how are you" | **كيف الحال** | كيف (alone), شخبارك |
| "how can I help you" (service register) | **كيف اقدر اخدمك** | شو تبي, شو تبغى |
| "please" / من فضلك | **لو سمحت** / إذا ممكن | لو تكرم |
| "a lot / very" / كثير (casual) | **واجد** (with ج jeem, NOT ي yaa) | وايد (wrong spelling) |
| "no problem" / لا بأس | **ما مشكلة** | ما في مشكلة, تكفون لا تشلون هم |
| أين | وين | — |
| الآن | الحين | — |
| لماذا | ليش | — |
| جيد | ممتاز / طيب | زين (casual; not used by default) |
| مرحبا | حياكم الله / مرحبا / تفضلوا | هلا (casual; not used by default) |
| شكرا | مشكورين / يعطيكم العافية | — |
| (you're welcome) | العفو / تحت أمركم | — |

**Defaultly banned (Egyptian/Levantine/Iraqi):** إزاي, عايز, بتاع, دلوقتي, كده, يلا, شو بدك, هلق, كتير, منيح, شلون, وش, هسه. **Defaultly banned (MSA in dialogue):** ماذا, أين, الآن, إذًا, حيث, إن, أنّ, كي, بل, سوف (bare form).

## Current state — as of 2026-05-20

**Phases done so far:**
- **P0 — Foundation & Conventions:** ✅ DONE. PR #1 (`feat(p0): foundation & conventions`).
- **P1 — LLM Adapter & Chat Loop:** ✅ DONE on PC1, live Omani greeting from Gemini 2.5-flash verified. PR #2 (`feat(p1): LLM adapter + Telegram + orchestrator`).

PR status on GitHub: check `https://github.com/basilalshukaili/omani-reception/pulls` — Basil typically reviews each PR before merging.

**P1 gate evidence** — `python scripts/smoke_test_p1.py` produced:
```
وعليكم السلام ورحمة الله وبركاته، حياكم الله في شركة الواحة للخدمات،
معاكم سارة موظفة الاستقبال. كيف اقدر اخدمكم؟
```
Authentic Muscat-style Omani, plural-of-respect, no banned tokens. ~$0.001 spent.

**Verified gates on PC1:**
- `pytest -m unit` → **166/166 passed in 9.46s**
- `ruff check` / `ruff format --check` → clean (48 files)
- `mypy engine` → 0 issues in 30 source files
- `python -m engine.cli --version` → `reception, version 0.1.0`
- `python -m engine.cli health --business generic_demo` → exit 0
- `python -m engine.cli chat --help` → shows `--no-telegram` flag
- Live Gemini 2.5-flash smoke test → PASS

**Deferred (pending Docker on PC2):**
- Full `docker compose up` boot (Postgres+pgvector+Redis live)
- Live Telegram polling round-trip — Basil sends `/start` to `@techmate_reception_bot`, bot responds via real polling loop
- Redis-backed session (currently in-memory; lands in P2)

**Cost-to-date: ~$0.001 of $5.00.**

## What to do first when you resume on PC2

```powershell
# 1. Confirm you're on the Docker-enabled machine
docker --version
docker compose version

# 2. Pull latest from GitHub (P0 + P1 should be there, possibly merged into main)
git pull --rebase origin main

# If PRs aren't merged yet, fetch and check out the latest feature branch:
#   git fetch origin
#   git checkout feat/p1-llm-adapter  (or main if merged)

# 3. Set up the local env (one-time per machine)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# 4. Copy the env template and fill in real values
copy .env.example .env
# Basil's keys (already used on PC1, copy verbatim):
#   TELEGRAM_BOT_TOKEN=8919867594:AAE8sqTILla2SkNKf38UdIn8uxRYbdwquMw
#   TELEGRAM_ADMIN_CHAT_ID=880315854
#   GEMINI_API_KEY=AIzaSyBZW3HiYSwnohs4G7-Ng46dqFhzMWSRxxI
# Bot: @techmate_reception_bot, chat_id 880315854 for /teach admin access.

# 5. Verify the existing P0 + P1 baseline
python -m engine.cli --version            # → reception, version 0.1.0
python -m engine.cli health --business generic_demo
pytest -m unit                             # → 166 passed
ruff check engine tests
mypy engine
python scripts/smoke_test_p1.py            # → live Gemini Omani greeting (PASS)

# 6. Bring up Docker stack (the big new thing on PC2)
docker compose up -d
docker compose ps                          # postgres + redis healthy
docker compose logs postgres | tail -20    # confirm pgvector + pg_trgm extensions ran
```

If all green, you're ready for **P2**.

To LIVE-test the Telegram bot (any time after the above):
```powershell
python -m engine.cli chat --business generic_demo
# Then on Basil's Telegram: send /start to @techmate_reception_bot
# Bot replies with an Omani greeting. Ctrl-C to stop the bot.
```

## Next phase — P2: Memory & RAG

**Scope (from PLAN.md §13):**
- **Replace `InMemorySessionStore` with `RedisSession`** behind the same interface
- **Postgres `kb_chunk` table** (the real schema, replacing the P0 stub in `infra/postgres/init.sql`)
- **Arabic normalizer** in `engine/rag/arabic_normalizer.py` — tashkeel removal, alef variants (ا/أ/إ/آ → ا), yaa variants (ي/ى → ي), taa marbuta (ة/ه), tatweel, light stemming via CAMeL Tools
- **Hybrid retriever** in `engine/rag/retriever.py` — BM25 via Postgres tsvector + dense via pgvector + RRF fusion (k=60), top-K from config
- **Embedding adapter** — Gemini `text-embedding-004` (free in tier)
- **Ingest script** in `scripts/ingest.py` — walks `businesses/<biz>/knowledge/`, chunks (~400 tokens, 60 overlap), embeds, persists to `kb_chunk`
- **Rolling summarization** in `engine/memory/summarizer.py` — when session exceeds `summarize_after_turns`, compress oldest half into Arabic summary
- **Long-term memory** `engine/memory/long_term.py` — `customer_memory(chat_id, business_id, fact_text, fact_embedding, source, created_at)` retrieval at turn start
- **Orchestrator hookup** — retrieve KB context + long-term facts + style retrieval (P4 will add this last one); inject into system prompt
- **Add `tools_file` / `phrase_dir` / `examples_file` / `knowledge_dir` to BusinessConfig schema** (deferred from P0)
- ADR-0003 (pgvector), ADR-0004 (arabic retrieval strategy)

**Gate:** bot answers ≥5 questions from a seeded `generic_demo` knowledge base correctly, in Omani Arabic. Memory persists across two messages in one conversation. Long-term memory recalls a fact from a prior session.

**Estimated cost:** ~$0.05 (Gemini Flash + free text-embedding-004 calls).

**Workflow:**
1. `git checkout -b feat/p2-memory-rag` (off latest `main` after PR #2 merges)
2. Use parallel sub-agents for: ingest pipeline, retriever, Arabic normalizer, Redis session, long-term memory, ADRs, tests
3. **Seed `businesses/generic_demo/knowledge/`** with 4-6 short markdown files (services, hours, pricing, location, FAQs, policies) — Basil can author these in Arabic before P2 starts, or Claude can draft and Basil corrects
4. Verify gate: real questions through Telegram → grounded answers
5. Open PR #3, write `docs/phase_reports/phase_2.md`

## Pending items / open questions (read before starting P1)

1. **`tools_file` / `phrase_dir` / `examples_file` / `knowledge_dir` paths** are in PLAN.md §10 but NOT yet in `engine/config/schema.py`. They're consumed in P2 (ingest) and P3 (tools). Decide in P2: either add them to schema, or hardcode `businesses/<id>/knowledge/`, `phrases/`, etc. as conventions. Recommendation: add to schema with defaults.
2. **Live correction loop `/teach` command** is specified in PLAN.md §6.9 and §10. Wire it in P4 (dialect) or earlier if you want Basil to start testing dialect before the full layer lands. Storage: Postgres `dialect_correction(input_text, wrong_output, corrected_output, reason, intent_guess, applied_at, applied_by)`. Apply via `scripts/apply_corrections.py`.
3. **`gh` CLI path on Windows.** Installed at `C:\Program Files\GitHub CLI\gh.exe`. If `gh` isn't on the shell PATH, invoke via full path: `& "C:\Program Files\GitHub CLI\gh.exe" pr create ...`. Restart PowerShell to get it on PATH automatically.
4. **GitHub Actions CI status.** First CI run on PR #1 may have flaked. If failing, the workflow is at `.github/workflows/ci.yml` — likely a small Python-version or dependency issue, debug from the run logs.

## Memory and Obsidian vault

- The original session wrote memory files to `C:\Users\basil\.claude\projects\C--Users-basil-Share-reception\memory\` on the first machine. **These will NOT transfer to a different Windows username or repo path.** All load-bearing facts have been re-stated in this HANDOFF.md and in PLAN.md so memory loss is non-fatal.
- If the Obsidian vault MCP server (`obsidian-brain`) is connected, **do not auto-read** the vault for general questions — only on explicit `/brain-save` or "check my notes" requests. See global `CLAUDE.md`.
- At the end of a substantive work session, write one lean session note to `Claude Sessions/YYYY-MM-DD - Reception P<N>.md` in the vault. 5-15 bullets max.

## How Basil works

- He approves plans, then expects autonomous execution through phase gates with end-of-phase reports.
- Phase reports go in `docs/phase_reports/phase_<n>.md` (format ratified in ADR-0009).
- He reviews each PR before merging — wait for his merge, don't auto-merge.
- He'll occasionally edit `PLAN.md` directly on GitHub (web UI) — `git pull --rebase` to sync. His edits are canonical.
- Native-speaker corrections to phrasings come in real time, often by him just saying "use X instead of Y." Persist these to `engine/dialect/banned_tokens.yaml` (lands in P4), to `businesses/<biz>/phrases/<intent>.yaml`, and to the memory file `omani-dialect-corrections.md` (when memory is available).

## What "done" looks like (PLAN.md §16 — the 14-point acceptance checklist)

1. One-command boot (`docker compose up`) — needs Docker
2. Provider-agnostic LLM proven via config swap
3. Telegram round-trip for ≥10 representative customer questions in Omani
4. Function calling proven (`book_appointment` stub end-to-end)
5. Dialect golden set ≥90% on `gemini-2.5-flash`
6. Memory works (in-conversation + across-session)
7. Security red-team passes 100%
8. Observability: log + trace + cost ledger for every conversation
9. Cost computable within 5% of provider-reported, total ≤ $5
10. p95 latency <6s
11. Onboarding doc verified: second dummy business in <30 min
12. All 9 ADRs written
13. All phase reports committed
14. Native-speaker review gate explicit before live customer rollout

---

**You now have everything needed to resume. Open `PLAN.md` for the full architecture, `docs/phase_reports/phase_0.md` for what's already shipped, and then start P1.**

If Basil tells you to start: spawn parallel sub-agents (LLM adapters, Telegram channel, Orchestrator, Tests) on a fresh `feat/p1-llm-adapter` branch. Verify gate before opening PR #2.
