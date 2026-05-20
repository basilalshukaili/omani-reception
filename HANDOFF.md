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
2. **Gemini is the only live LLM provider for v1.** Claude/OpenAI adapters are written and unit-tested with mocked HTTP, but no live key is required. Default model: `gemini-1.5-flash` for normal turns, `gemini-1.5-pro` for evaluation/judge calls.
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

**Phase P0 — Foundation & Conventions: ✅ DONE** (or pending PR #1 merge — verify on GitHub).

Verified locally on the original dev machine:
- `python -m engine.cli --version` → `reception, version 0.1.0`
- `python -m engine.cli health --business generic_demo` → exit 0, prints Arabic persona name correctly
- `pytest -m unit` → 20/20 passed in 0.27s
- `ruff check engine tests` → clean
- `ruff format --check engine tests` → clean
- `mypy engine` → 0 issues across 19 files
- `docker-compose.yml` → structurally valid (`python scripts/verify_compose.py`)

**Deferred:** full `docker compose up` boot — Docker Desktop was not installed on the original dev machine. **You should be on the Docker-enabled machine now; verify with `docker --version && docker compose version`.**

PR #1: `https://github.com/basilalshukaili/omani-reception/pull/1` (titled `feat(p0): foundation & conventions`).

## What to do first when you resume

```powershell
# 1. Confirm you're on the right machine
docker --version
docker compose version

# 2. Pull latest from GitHub (may include the merged P0 PR)
git pull --rebase origin main

# 3. Set up the local env (one-time per machine)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# 4. Copy the env template and fill in real values
copy .env.example .env
# Then edit .env — at minimum set:
#   TELEGRAM_BOT_TOKEN  (already created: @techmate_reception_bot — Basil has the token)
#   GEMINI_API_KEY      (Basil has this)
#   TELEGRAM_ADMIN_CHAT_ID=880315854   (already in .env.example default — keep)

# 5. Verify the existing P0 baseline
python -m engine.cli --version            # → reception, version 0.1.0
python -m engine.cli health --business generic_demo
pytest -m unit                             # → 20 passed
ruff check engine tests
mypy engine
docker compose config                      # → should print resolved YAML; if errors, debug
```

If all green, you're ready for **P1**.

## Next phase — P1: LLM Adapter & Chat Loop

**Scope (from PLAN.md §13):**
- `LLMProvider` abstract base class in `engine/llm/base.py` + concrete adapters:
  - `engine/llm/gemini.py` — **live**, uses `google-genai` SDK
  - `engine/llm/claude.py` — **mocked-tested**, uses `anthropic` SDK
  - `engine/llm/openai.py` — **mocked-tested**, uses `openai` SDK
  - `engine/llm/factory.py` — picks provider from config / env override
  - `engine/llm/normalize.py` — unifies tool-call schemas across providers
- `engine/channels/base.py` — `Channel` ABC (works for Telegram now, voice later)
- `engine/channels/telegram.py` — long-polling adapter (use `python-telegram-bot` v21)
- `engine/core/orchestrator.py` — turn-by-turn loop: receive → call LLM with bare system prompt → reply
- Wire `/start` to a configurable Omani greeting from `businesses/generic_demo/config.yaml.persona.signature_open` (add this field to schema if not present — see deferred items below)
- ADR-0002 (LLM abstraction), ADR-0006 (channel abstraction)

**Gate:** `/start` on Telegram returns an Omani greeting via Gemini. Same code works with `LLM_PROVIDER=claude` and `LLM_PROVIDER=openai` env override (mocked in tests; gracefully fails with a clear "no API key" message live if no key is provided).

**Estimated cost:** under $0.10 for testing (Gemini Flash is cheap).

**Workflow:**
1. `git checkout -b feat/p1-llm-adapter`
2. Use the `Agent` tool with `general-purpose` sub-agents in parallel for: LLM adapters, Channel adapter, Orchestrator, Tests. Coordinate via `TaskCreate`.
3. Verify gate yourself: `pytest`, then manually `/start` to the Telegram bot.
4. Open PR #2, write `docs/phase_reports/phase_1.md`, wait for Basil's review.

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
5. Dialect golden set ≥90% on `gemini-1.5-flash`
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
