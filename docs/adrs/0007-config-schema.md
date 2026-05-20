# ADR-0007: Configuration schema

- **Status:** Accepted
- **Date:** 2026-05-20
- **Deciders:** Basil Al-Shukaili (project lead), Claude (engineering)
- **Phase:** P0 — Foundation & Conventions
- **Related:** [PLAN.md](../../PLAN.md) §10 (Configuration Schema), §1.1 (Guiding principles — "Configuration over code"), §8 (Security)

## Context

The Omani Reception engine is business-agnostic: a new business is onboarded by dropping a folder at `businesses/<name>/` containing a YAML config, a knowledge base, an Omani phrase library, few-shot examples, and a tools manifest. The engine never imports from `businesses/`, and **zero engine code changes per business** is a hard architectural rule (PLAN.md §1.1).

This makes the per-business configuration file the contract between the engine and every business that ever runs on it. The schema must express: business identity and hours; persona (Arabic display name, role, voice, region, register, response-style caps); LLM provider and model; embedding provider; RAG knobs (top-K, rerank flag, chunk sizing); dialect enforcement settings (threshold, judge gating, banned-token extras); memory settings; channel settings (Telegram token env-var, allowed chat IDs); security knobs (rate limits, PII consent, allowed languages); and observability settings. PLAN.md §10 lays out the full shape.

Non-functional requirements that shape the decision: (a) human-authored — small-business operators or our docs writers must be able to edit it without an IDE; (b) strict at startup — typos must fail loud with a line-pointing error, not produce silently-degraded behaviour at turn time; (c) secret-free — no API keys, tokens, or passwords ever in the file; (d) tooling-friendly — editors should offer completion and inline validation; (e) Arabic-friendly — display name, persona voice, signature close, and many nested strings are Arabic and must round-trip cleanly.

## Decision

The business contract is expressed in **YAML**, parsed into **Pydantic v2** models, with environment-variable interpolation handled by the loader.

Concrete specifics:

- **One file per business** at `businesses/<name>/config.yaml`. Sibling folders hold knowledge, phrases, examples, tools — all referenced by relative paths in the config (`knowledge_dir`, `phrase_dir`, `examples_file`, `tools_file`).
- **Schema lives at** `engine.config.schema.BusinessConfig` (and child models). The top-level groups follow PLAN.md §10: `business`, `persona`, `llm`, `embedding`, `rag`, `dialect`, `memory`, `channels`, `security`, `observability`, plus the path pointers.
- **Strict mode everywhere:** every Pydantic model carries `model_config = ConfigDict(extra="forbid")`. Typos in keys (`treshold` vs. `threshold`) fail validation at startup with a path-pointing error.
- **Env-var interpolation in the loader.** The loader resolves `${VAR}` and `${VAR:default}` after YAML parse, before Pydantic validation. Missing vars without a default raise a clear loader error. This keeps secrets in `.env` and never in the YAML.
- **Loaded by:** `engine.config.loader.load_business(business_id: str) -> BusinessConfig`. Called once at startup; the resulting object is treated as immutable for the process lifetime.
- **JSON Schema export:** Pydantic emits the JSON Schema for `BusinessConfig` to `docs/schemas/business_config.schema.json`. Editors with YAML Language Server (VS Code, JetBrains) pick this up via a `# yaml-language-server: $schema=…` header at the top of each `config.yaml`. The export task is on the P0.5 / P1 runway and is owned by this ADR.
- **Validation failures exit the process.** No partial startup. The error message includes the file path, the YAML path (e.g., `persona.response_style.max_words_casual`), and the expected type — copy-paste friendly for the operator.

## Alternatives considered

### Option A — TOML
- **Pros:** First-class in `pyproject.toml`; comments supported; widely understood.
- **Cons:** Less ergonomic for deeply nested structures (`hours.monday`, lists of intent variants, tool schemas); multi-line strings are awkward; Arabic strings work but feel out of place in a format dominated by `key = value` lines.
- **Verdict:** Rejected because the config is *deeply nested* (persona → response_style → caps; channels → telegram → allowed_chat_ids; tools → schemas) and non-engineers are expected to edit it.

### Option B — JSON
- **Pros:** Ubiquitous; trivially validatable; native to many languages.
- **Cons:** No comments; trailing-comma issues; multi-line strings require `\n` escapes which are hostile to Arabic content (persona voice descriptions, signature closes). Operators editing JSON by hand make silent syntax errors regularly.
- **Verdict:** Rejected because human authoring is a primary use case.

### Option C — Python files (`businesses/<biz>/config.py`)
- **Pros:** Maximum flexibility; no separate parser; type checking via mypy out of the box.
- **Cons:** A business config that is arbitrary Python code violates the "configuration over code" principle (PLAN.md §1.1, rule 3) — it makes the boundary between engine and business porous, opens an injection surface (`businesses/<biz>/config.py` can `import os; os.system(...)`), and makes diffs hard to review. It also breaks the rule that the engine never imports from `businesses/`.
- **Verdict:** Rejected on principle and on safety.

### Option D — dotenv-only (`.env` files)
- **Pros:** Trivial to parse; native to `python-dotenv`; secret-friendly.
- **Cons:** No nesting; cannot express hours, tool schemas, persona objects, response-style caps, or any list of intents — the schema is fundamentally tree-shaped and `.env` is flat.
- **Verdict:** Rejected for the business config. `.env` remains the home for secrets only (Telegram tokens, Gemini API key, Postgres password), referenced from YAML via `${VAR}` interpolation.

## Consequences

### Positive
- One file, one contract: the entire behaviour of a business is reviewable in a single ~80-line YAML file plus its sibling data folders.
- Startup validation surfaces typos and missing required fields before the bot ever connects to Telegram. Operators get a clear error pointing to the offending line.
- Secrets are physically separated: YAML can be committed to the repo (and to per-business forks) without ever containing a key.
- Editors with YAML LSP autocomplete `business.*`, `persona.*`, `dialect.*` and inline-validate types thanks to the exported JSON Schema.
- The engine's view of the business is a typed Python object, not a dict — every downstream module (orchestrator, retriever, validator, channels) gets IDE help and mypy coverage.

### Negative / accepted trade-offs
- YAML's whitespace sensitivity occasionally bites first-time editors. We mitigate with the LSP schema header and with examples in `docs/onboarding_a_business.md`.
- A schema change in `engine.config.schema` is a breaking change for every business config that uses the affected field. We commit to versioning the schema (`BusinessConfig.schema_version`) and writing a migration note in the relevant ADR when this happens.
- Env-var interpolation is loader-side, not Pydantic-side; the loader is therefore part of the validated contract and has its own unit tests (`tests/unit/test_config_schema.py`).

### Follow-ups
- Export `docs/schemas/business_config.schema.json` at the end of P0.5 / start of P1; wire it into `make schemas` and CI.
- Add a YAML LSP schema header to `businesses/generic_demo/config.yaml` once the JSON Schema is exported.
- Document in `docs/onboarding_a_business.md` how to add a new business config and how to interpret a startup validation error (P7).
- When tool schemas (`businesses/<biz>/tools.yaml`) and phrase libraries (`businesses/<biz>/phrases/*.yaml`) land in P3 and P4 respectively, they get their own Pydantic models under `engine.config.schema` and are validated by the same loader.
