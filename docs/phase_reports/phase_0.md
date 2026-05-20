# Phase Report — P0: Foundation & Conventions

- **Phase:** P0 — Foundation & Conventions
- **Status:** ✅ Gate passed (one item deferred — see §Deferred)
- **Date:** 2026-05-20
- **Duration:** ~25 minutes (planning → first push → P0 done)
- **Cost-to-date:** $0.00 (no LLM/embedding calls made)
- **Remaining build budget:** $5.00 of $5.00

## What was built

### Foundation (lead agent)
- `pyproject.toml` — Python 3.11+, uv-friendly, ruff + mypy + pytest configs
- `.env.example`, `.dockerignore`, `Makefile` (developer shortcuts)
- Package tree under `engine/` with sub-packages for every subsystem in PLAN §1.3
- `engine/__init__.py` with `__version__ = "0.1.0"`

### Docker stack (sub-agent: Docker)
- `docker-compose.yml` — services: `postgres` (pgvector/pgvector:pg16), `redis` (7-alpine), `app` (built locally). Healthchecks on both data services; `app` depends on `service_healthy` for both.
- `infra/docker/Dockerfile` — slim-bookworm + `uv` for fast deps install; non-root `app` user (uid 1000); LF-line-ending entrypoint.
- `infra/docker/entrypoint.sh` — waits for Postgres + Redis, prints banner, exec's CMD.
- `infra/postgres/init.sql` — enables `vector` + `pg_trgm`; sanity `_health_check` table; real `kb_chunk` table stubbed as comments (lands in P2).

### Config layer (sub-agent: Config)
- `engine/config/schema.py` — Pydantic v2, 16 sub-models, `extra="forbid"` everywhere, slug + HH:MM + day-name validators.
- `engine/config/loader.py` — `load_business_config()`, `${VAR}` and `${VAR:default}` interpolation, `find_repo_root()`, `export_json_schema()`. Wraps validation errors as `ConfigError` with file-path prefix.
- `businesses/generic_demo/config.yaml` — Muscat / Sahili / official-respectful Gemini-default sample. Includes Basil's chat_id `880315854` as `channels.telegram.admin_chat_ids`.

### Engine skeleton + CLI (sub-agent: Engine)
- `engine/cli.py` — click group `cli` (= `main` for `[project.scripts]`), `--version`, `--help`, sub-commands `health`, `chat`, `ingest`, `eval` (latter two are P2/P4 stubs). Reconfigures stdout/stderr to UTF-8 before logging is set up so Arabic renders on Windows consoles.
- `engine/core/types.py` — `Role` (StrEnum), `Attachment`, `ChannelMessage`, `Turn`, `ToolCall`, `ToolResult`, `ToolSchema`, `LLMResponse`, `TokenUsage`. All Pydantic v2 with `extra="forbid"`.
- `engine/core/session.py` — `ConversationSession` model with stubbed methods; `# TODO(P2): wire Redis backing`.
- `engine/observability/logging.py` — `configure_logging(level, fmt)` (JSON in prod / console in dev, auto-selected from `RECEPTION_ENV`); `get_logger(name)` helper.

### Testing scaffolding (sub-agent: Tests)
- `tests/conftest.py` — `repo_root`, `tmp_business_dir`, `valid_config_yaml`, `invalid_config_yaml` fixtures + `set_env` helper.
- `tests/unit/test_config_loader.py` — happy-path load, parametrized slug validation, deliberate-failure config, env-var interpolation, missing-business `FileNotFoundError`.
- `tests/unit/test_cli_health.py` — `CliRunner` against `engine.cli.main` for `health`, `--help`, `--version`, and unknown-business non-zero exit.
- `tests/unit/test_imports.py` — one test per engine module for early syntax/circular-import detection.
- `tests/README.md` — how to run, layout, markers.

### GitHub collaboration (sub-agent: Collab)
- `CONTRIBUTING.md` — setup, branch policy, Conventional Commits, PR flow, secrets rules, dialect contribution rules, ADR/phase-report conventions.
- `CODEOWNERS` — `* @basilalshukaili` (TODO: add friend's handle when joining).
- `.github/PULL_REQUEST_TEMPLATE.md` — required: dialect impact + cost impact + test plan.
- `.github/ISSUE_TEMPLATE/{bug_report,feature_request,config}.{md,yml}`.
- `.github/workflows/ci.yml` — Python 3.11 + 3.12 matrix; ruff check + format check + mypy + pytest with coverage.

### ADRs (sub-agent: ADRs)
- `docs/adrs/0001-language-and-framework.md` — Python / no web framework / click / structlog / Pydantic v2 / uv / hatchling. MADR-lite.
- `docs/adrs/0007-config-schema.md` — Pydantic v2 + YAML at `businesses/<biz>/config.yaml`.
- `docs/adrs/0009-methodology-and-phase-gates.md` — 8 phases with demo-able gates + per-phase reports.

## Gate verification

| Check | Result | Evidence |
|---|---|---|
| `python -m engine.cli --version` | ✅ pass | prints `reception, version 0.1.0` |
| `python -m engine.cli --help` | ✅ pass | lists `health, chat, ingest, eval` |
| `python -m engine.cli health --business generic_demo` | ✅ pass | exit 0; persona `سارة` renders correctly on Windows console |
| `pytest -m unit` | ✅ pass | **20/20 passed in 0.27s** |
| `ruff check engine tests` | ✅ pass | "All checks passed!" |
| `ruff format --check engine tests` | ✅ pass | "27 files already formatted" |
| `mypy engine` | ✅ pass | "Success: no issues found in 19 source files" |
| `docker-compose.yml` structural validity | ✅ pass | `scripts/verify_compose.py` — all 3 services + 2 named volumes verified |
| Full `docker compose up` boot | ⏸ deferred | **Docker Desktop not installed on this Windows host** — see §Deferred |

## Decisions made during P0 (not in PLAN)

| Decision | Why |
|---|---|
| Added `disable_error_code = ["untyped-decorator"]` to mypy config | click's decorator signatures are untyped at the library level; same idiom as ruff's `B008` ignore. Avoids 8 false-positive errors on every click command without weakening type checks elsewhere. |
| `_ensure_utf8_stdio()` runs before imports in `engine/cli.py` (E402-suppressed) | Required for Arabic console rendering on Windows. Documented inline. |
| `class Role(StrEnum)` instead of `class Role(str, Enum)` | Cleaner Python 3.11+ idiom; ruff `UP042`-recommended; semantically identical. |
| `infra/docker/Dockerfile` adds `postgresql-client` + `redis-tools` to runtime image | The entrypoint script invokes `pg_isready` and `redis-cli` for health waits. Could be slimmed later by switching to `nc`/Python probes. |
| `eval` subcommand internal callable is `eval_cmd` (not `eval`) | Avoid shadowing the Python builtin. The CLI surface still says `eval`. |
| Added `scripts/verify_compose.py` | YAML-level validation when Docker isn't installed. Will be wired into CI in P5+. |

## Deviations from PLAN

- **Embedding default** is `text-embedding-004` (Gemini, free) instead of OpenAI `text-embedding-3-large`. Already reflected in PLAN.md after user input on cost cap.
- **LLM default** is Gemini-only live for v1. Adapters for Claude/OpenAI will still be written + unit-tested with mocked HTTP in P1, just not exercised live without keys.
- **Phase reports** are landing in `docs/phase_reports/` (this file is the first). Format ratified in ADR-0009.

## Deferred

| Item | Reason | When |
|---|---|---|
| Full `docker compose up` end-to-end boot | Docker Desktop not installed on user's machine (verified during P0) | When user installs Docker Desktop — runbook will document. Compose YAML is structurally valid and the Dockerfile/init.sql are syntactically correct, so first boot should be clean once Docker is present. |
| `tools_file` / `phrase_dir` / `examples_file` / `knowledge_dir` schema fields | Visible in PLAN.md §10 but not yet in `BusinessConfig` schema; they're not consumed until P2 (ingestion) and P3 (tools) | P2 (paths needed for `scripts/ingest.py` to find knowledge files); P3 (paths needed for tool registry) |
| Coverage threshold enforcement | Marked TODO in `.github/workflows/ci.yml` | P5+ (security & test maturity phase) |

## What's open / risks for P1

1. **Telegram polling lifecycle.** Long-polling needs a graceful shutdown story (signal handlers, cancellation). Will think through in P1.
2. **Gemini SDK choice.** The official SDK is `google-genai` (newer) vs `google-generativeai` (older). Pinning `google-genai` in P1.
3. **Mock LLM strategy in tests.** Need a clean approach — likely a `MockLLMProvider` class returning configured responses, used by adapter contract tests.
4. **gh PATH on the lead agent's shell.** Workaround: invoke `gh.exe` via full path. Documented in `PLAN.md §18.5`.

## Files added in this commit (count)

- 50 source/config files
- 4 new docs (3 ADRs + this phase report)
- All in 1 commit on `main` (no feature branch — P0 is the foundation; subsequent phases use feature branches per `CONTRIBUTING.md`)

## Reviewer prompts for Basil

1. **Verify the local repo** — `git log --oneline` should show 3 commits (initial plan, plan corrections, P0 foundation) all pushed to `https://github.com/basilalshukaili/omani-reception`.
2. **Try a local health check** — once you `pip install -e ".[dev]"` (or `uv sync`) in your shell, run `python -m engine.cli health --business generic_demo`. Should print Arabic correctly.
3. **Install Docker Desktop** when convenient so we can verify the full `docker compose up` boot. Not blocking for P1, but blocking for the absolute "one-command boot" acceptance criterion (PLAN §16 #1).
4. **Review the persona/lexicon in `businesses/generic_demo/config.yaml`** — flag anything that doesn't sound right. Corrections will get encoded in P4's lexicon + phrase library; for now they live in config.

## Next phase

**P1 — LLM Adapter & Chat Loop.** Provider interface + Gemini/Claude/OpenAI adapters (mocked-tested), Telegram channel adapter (long-polling), orchestrator skeleton, `/start` greeting. ADR-0002 (LLM abstraction), ADR-0006 (channel abstraction). Expected ~30-45 min.
