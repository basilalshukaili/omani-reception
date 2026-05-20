# ADR-0001: Language and framework

- **Status:** Accepted
- **Date:** 2026-05-20
- **Deciders:** Basil Al-Shukaili (project lead), Claude (engineering)
- **Phase:** P0 — Foundation & Conventions
- **Related:** [PLAN.md](../../PLAN.md) §2 (Tech Stack & Rationale), §3 (Provider-Agnostic LLM Layer)

## Context

The Omani Reception engine is a chat-only AI receptionist that converses in authentic Omani Khaleeji Arabic over Telegram. The system is a single deployable unit (cleanly modular, not microservices — premature for v1) that needs to: drive LLM providers (Gemini live, Claude/OpenAI behind the same adapter), do Arabic-aware retrieval over Postgres + pgvector, run a multi-layer dialect enforcement pipeline, and expose a CLI for health checks, ingestion, chat, and evaluation.

The non-functional requirements that shape this decision are: (a) **first-class Arabic NLP** support including normalization and light stemming; (b) **first-class LLM SDK ergonomics** for Gemini, Claude, and OpenAI with streaming and tool calling; (c) **strict, declarative configuration** validated at startup with editor support; (d) **structured logging** ready for OpenTelemetry; (e) **fast iteration and reproducible builds** on a Windows dev host and Linux container; (f) **no premature web surface** — Telegram long-polling is the only entry point in v1, and an admin/webhook surface can be added later without rework.

The team is two developers (Basil + friend, non-concurrent) collaborating via feature-branch PRs. There is no operations team; whatever we pick has to be easy to install, lock, and reproduce on a fresh machine. The cost ceiling for the entire build is $5 USD total, so the language and tooling cannot drag in paid runtime dependencies.

## Decision

We adopt the following stack for the engine and CLI:

- **Language:** **Python 3.11+**. Standard async/await, structural pattern matching, and modern typing are all available.
- **Web framework:** **None for v1.** Telegram long-polling via `python-telegram-bot` v21 is the only entry point. A minimal FastAPI surface (admin / `/metrics` / webhook mode) is allowed to land in P5+ when it is actually needed.
- **CLI:** **click**. `python -m engine.cli {chat,ingest,health,eval,forget}` is the only operator-facing surface.
- **Logging:** **structlog**. JSON in production, pretty console in dev. Every turn emits structured key-value records that feed the cost ledger and OpenTelemetry spans.
- **Config and shared types:** **Pydantic v2**. The `BusinessConfig` schema (ADR-0007) and every internal type that crosses an adapter boundary (`ChannelMessage`, `Turn`, `ToolCall`, `LLMResponse`) is a Pydantic model with `extra="forbid"`.
- **Dependency management:** **uv** with `pyproject.toml`. Lockfile committed.
- **Build backend:** **hatchling** declared in `[build-system]` of `pyproject.toml`.
- **Lint and types:** **ruff** (lint + format) and **mypy** (strict mode on engine package).
- **Tests:** **pytest**, `pytest-asyncio`, `pytest-httpx`, `hypothesis` for normalizer edge cases.

## Alternatives considered

### Option A — TypeScript / Node.js
- **Pros:** Single-language stack if a web admin is added; mature Telegram libraries; good async story.
- **Cons:** Arabic NLP ecosystem is significantly weaker (no equivalent of CAMeL Tools or PyArabic); LLM SDK ergonomics for our use case (tool-call normalization across three providers) are less direct; pgvector clients are less mature than in Python.
- **Verdict:** Rejected because the Arabic NLP and LLM-SDK quality-of-life gap is too large to bridge for a v1 with a tight budget.

### Option B — Go
- **Pros:** Single static binary; excellent concurrency; fast startup; easy ops.
- **Cons:** No Pydantic-equivalent for the kind of nested, validated, env-interpolated YAML config we need; LLM SDKs exist but are not the first-party ones the providers maintain most actively; Arabic NLP libraries are scarce.
- **Verdict:** Rejected because the configuration story alone would require us to write significant validation infrastructure, and the LLM SDKs are not first-class.

### Option C — FastAPI as the v1 front door
- **Pros:** Async, Pydantic-native, OpenAPI for free; would let us add a web admin and webhook mode immediately.
- **Cons:** Adds infrastructure surface area (reverse proxy, HTTPS termination, port exposure) that we do not need in v1. Telegram long-polling is strictly simpler and avoids any inbound network requirements on the dev host.
- **Verdict:** Rejected for v1. FastAPI can be added in P5+ for an admin / `/metrics` / webhook surface — it is on the runway, not in the path.

### Option D — Poetry or pip-tools instead of uv
- **Pros:** Both are mature; Poetry has wide adoption.
- **Cons:** uv is meaningfully faster (orders of magnitude on cold installs), produces a lockfile, and is becoming the modern default. Poetry's resolver is slow on large dependency graphs; pip-tools lacks the integrated environment management.
- **Verdict:** Rejected because uv is strictly better on speed and equivalent on lockfile guarantees, with no downside that affects this project.

## Consequences

### Positive
- First-class Arabic NLP via CAMeL Tools, PyArabic, and a custom Omani-aware overlay (ADR-0004 will ratify the retrieval-side details).
- First-class, provider-native LLM SDKs (`google-genai`, `anthropic`, `openai`) behind one narrow ABC — ADR-0002 will ratify the abstraction.
- Pydantic v2 enforces the business contract at startup; typos in `config.yaml` fail loud with a line-pointing error (ADR-0007).
- Fast, reproducible installs via `uv sync` on Windows dev hosts and inside the Docker image.
- structlog plus mypy strict mode catch a meaningful class of bugs before runtime; the engine has a small enough surface that strict typing is not a burden.

### Negative / accepted trade-offs
- Python's runtime is slower than Go or Rust. For a chat workload bounded by LLM latency (p95 target 6 s, dominated by network round-trips), this does not matter.
- No single-binary deployment artifact; we ship a Docker image instead. Acceptable because the deployment story is already Docker Compose (PLAN.md §17 assumption 2).
- mypy strict mode adds friction when integrating third-party libraries with weak type stubs; we accept this and use `# type: ignore[...]` narrowly where unavoidable.

### Follow-ups
- ADR-0002 will pin the LLM provider abstraction.
- ADR-0006 will pin the channel abstraction (Telegram now, voice later).
- ADR-0007 will pin the configuration schema in detail.
- If and when an admin/webhook surface is needed (P5+), FastAPI is the chosen framework — that introduction will be tracked as a separate ADR at that time.
