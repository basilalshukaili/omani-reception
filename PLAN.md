# PLAN — Omani Arabic AI Receptionist (General Scaffold)

**Status:** Draft for approval. Implementation is BLOCKED on user sign-off.
**Author:** Claude (Opus 4.7, 1M context)
**Date:** 2026-05-20
**Target repo root:** `C:\Users\basil\Share\reception`

---

## 0. Executive Summary

We will build a **provider-agnostic, business-agnostic, chat-only AI receptionist** that converses in authentic **Omani Khaleeji Arabic** over Telegram. The engine is a Python monolith (cleanly modular, not microservices — premature for v1) running in Docker Compose alongside Postgres+pgvector and Redis. A new business is onboarded by dropping a folder under `businesses/<name>/` containing a YAML config, a knowledge base, an Omani phrase library, few-shot examples, and a tools manifest. **Zero engine code changes per business.**

The hardest problem is not architecture — it is **keeping output authentically Omani end-to-end**. We address this with a seven-layer defense: prompt-embedded lexicon + phrase library + few-shot examples, style retrieval, rules-based dialect validator, optional LLM-as-judge, correction-retry loop, golden CI tests, and a human-review queue. We are honest that **without at least one native Omani reviewer in the loop, dialect quality has a verifiable ceiling**; that dependency is called out as a hard acceptance gate before any real-customer rollout.

We will deliver in **8 phases** with explicit demo-able gates, parallelizing within phases using Claude Code's native sub-agent tooling (since the Ruflo MCP layer referenced in CLAUDE.md is not actually connected in this environment — we'll proceed with the equivalent built-in primitives).

---

## 1. Architecture

### 1.1 Guiding principles

1. **Engine vs. business strict separation.** `engine/` is the reusable library; `businesses/<name>/` is pure config + data. The engine never imports from `businesses/`.
2. **Adapter pattern at every external seam.** LLM provider, channel (Telegram → Voice later), vector store, KV store, observability sink — all behind narrow interfaces.
3. **Configuration over code.** A business is a YAML manifest + a folder of assets. Anything that could vary per business lives there.
4. **Fail loud at boundaries, soft inside.** Reject malformed config at startup. Inside a conversation, degrade gracefully (e.g., RAG miss → still answer; tool error → apologize naturally; dialect-validator fail → retry with stricter prompt, fall back to canned phrase).
5. **Every decision has an ADR.** Future maintainers (and you) should know *why* we picked what we picked.

### 1.2 High-level diagram

```
                              ┌──────────────────┐
                              │   Telegram User  │
                              └────────┬─────────┘
                                       │  text
                              ┌────────▼─────────┐
                              │ Telegram Adapter │  (engine/channels/telegram.py)
                              └────────┬─────────┘
                                       │  ChannelMessage
                              ┌────────▼─────────┐
                              │   Orchestrator   │  (engine/core/orchestrator.py)
                              └────┬──┬──┬──┬────┘
              ┌────────────────────┘  │  │  └────────────────────┐
              │                       │  │                       │
        ┌─────▼─────┐         ┌───────▼──▼──────┐         ┌──────▼──────┐
        │  Security │         │  Session State  │         │   Dialect   │
        │  Pipeline │         │   (Redis)       │         │  Pipeline   │
        └─────┬─────┘         └────────┬────────┘         └──────┬──────┘
              │                        │                         │
              │                        │              ┌──────────┴───────────┐
              │                ┌───────▼────────┐     │ ┌────────┐ ┌───────┐ │
              │                │  Long-term Mem │     │ │Lexicon │ │Phrase │ │
              │                │  + RAG (pgvec) │     │ │        │ │Retrvr │ │
              │                └───────┬────────┘     │ └────────┘ └───────┘ │
              │                        │              │ ┌────────┐ ┌───────┐ │
              │                        │              │ │Validate│ │Correc.│ │
              │                        │              │ └────────┘ └───────┘ │
              │                        │              └──────────┬───────────┘
              │                        │                         │
              │                ┌───────▼─────────────────────────▼───────┐
              │                │   Prompt Builder (system + RAG + few-   │
              │                │   shot + style + state + tools schema)  │
              │                └────────────────────┬────────────────────┘
              │                                     │
              │                            ┌────────▼────────┐
              │                            │  LLM Provider   │
              │                            │  (Gemini / Claude/│
              │                            │   GPT, swappable)│
              │                            └────────┬────────┘
              │                                     │
              │                            ┌────────▼────────┐
              │                            │ Function-Calling│
              │                            │  Tool Executor  │
              │                            └────────┬────────┘
              │                                     │
              └─────────────────────────────────────▼
                                             Observability
                                  (logs, traces, cost — every step)
```

### 1.3 Folder structure (committed up front)

```
reception/
├── PLAN.md                          # this file
├── README.md                        # quickstart
├── docker-compose.yml               # one-command boot
├── pyproject.toml                   # uv / hatch managed
├── .env.example                     # all secrets templated
├── .gitignore
├── .dockerignore
│
├── engine/                          # BUSINESS-AGNOSTIC. never imports businesses/
│   ├── __init__.py
│   ├── cli.py                       # python -m engine.cli {chat,ingest,health,eval}
│   ├── config/
│   │   ├── loader.py                # Pydantic models, strict validation, JSON-Schema export
│   │   └── schema.py
│   ├── core/
│   │   ├── orchestrator.py          # the turn-by-turn loop
│   │   ├── session.py               # per-conversation state object
│   │   └── types.py                 # ChannelMessage, Turn, ToolCall, etc.
│   ├── llm/
│   │   ├── base.py                  # LLMProvider ABC
│   │   ├── gemini.py
│   │   ├── claude.py
│   │   ├── openai.py
│   │   ├── factory.py
│   │   └── normalize.py             # unifies tool-call schemas across providers
│   ├── memory/
│   │   ├── short_term.py            # Redis-backed conversation buffer
│   │   ├── long_term.py             # pgvector summaries / facts per chat_id
│   │   └── summarizer.py            # rolling summary when buffer > threshold
│   ├── rag/
│   │   ├── ingest.py                # markdown → chunks → embeddings
│   │   ├── retriever.py             # hybrid: BM25 (Postgres tsvector) + dense + RRF
│   │   ├── arabic_normalizer.py     # tashkeel, alef/yaa, taa marbuta
│   │   └── reranker.py              # cross-encoder rerank (optional, gated)
│   ├── dialect/
│   │   ├── lexicon.py               # MSA→Omani and disallowed-tokens tables
│   │   ├── style_retriever.py       # phrase-library RAG (separate index)
│   │   ├── validator.py             # rule scoring + optional LLM judge
│   │   ├── corrector.py             # retry loop with stricter prompt
│   │   └── examples_loader.py       # loads few-shot from business config
│   ├── prompts/
│   │   ├── system_builder.py        # assembles final system prompt
│   │   └── templates/               # jinja2 partials
│   │       ├── persona.j2
│   │       ├── dialect_rules.j2
│   │       ├── lexicon_table.j2
│   │       ├── few_shot.j2
│   │       ├── retrieved_context.j2
│   │       ├── tools_schema.j2
│   │       └── safety_rules.j2
│   ├── tools/
│   │   ├── base.py                  # Tool ABC, JSON-schema in/out
│   │   ├── registry.py              # loads from business tools.yaml
│   │   └── builtin/
│   │       ├── escalate_to_human.py
│   │       ├── log_lead.py
│   │       ├── check_business_hours.py
│   │       └── handoff_message.py
│   ├── security/
│   │   ├── injection_guard.py       # prompt-injection input sanitizer
│   │   ├── pii_redactor.py          # phones, emails, IDs out of logs
│   │   ├── rate_limiter.py          # per chat_id token bucket
│   │   └── output_validator.py      # no system-prompt leakage, no English fallback, etc.
│   ├── observability/
│   │   ├── logging.py               # structlog config, JSON in prod, pretty in dev
│   │   ├── tracing.py               # OpenTelemetry, optional Langfuse export
│   │   ├── cost_tracker.py          # tokens × price-per-1k by provider
│   │   └── metrics.py               # prometheus-style counters
│   └── channels/
│       ├── base.py                  # Channel ABC (works for Telegram now, Voice later)
│       └── telegram.py
│
├── businesses/                      # BUSINESS-SPECIFIC. only data + config here.
│   └── generic_demo/
│       ├── config.yaml              # the business contract (see §11)
│       ├── knowledge/               # raw markdown / txt for RAG ingestion
│       │   ├── about.md
│       │   ├── services.md
│       │   ├── hours.md
│       │   ├── pricing.md
│       │   ├── location.md
│       │   ├── faqs.md
│       │   └── policies.md
│       ├── phrases/                 # Omani phrase library, by intent
│       │   ├── greetings.yaml
│       │   ├── apologies.yaml
│       │   ├── confirmations.yaml
│       │   ├── clarifications.yaml
│       │   ├── farewells.yaml
│       │   ├── small_talk.yaml
│       │   └── escalations.yaml
│       ├── examples/
│       │   └── conversations.yaml   # 10-15 full sample turns in Omani
│       └── tools.yaml               # tool defs + per-tool config (mock endpoints OK in v1)
│
├── tests/
│   ├── unit/
│   │   ├── test_llm_adapters.py     # mocked HTTP
│   │   ├── test_arabic_normalizer.py
│   │   ├── test_dialect_validator.py
│   │   ├── test_security.py
│   │   └── test_config_schema.py
│   ├── integration/
│   │   ├── test_rag_pipeline.py     # real pgvector, real embedding (or stubbed)
│   │   ├── test_tool_execution.py
│   │   └── test_memory.py
│   ├── dialect/
│   │   ├── golden_conversations.yaml # 40+ canonical turns
│   │   └── test_golden.py
│   └── e2e/
│       └── test_telegram_loop.py    # uses Telegram test mode or stub
│
├── scripts/
│   ├── ingest.py                    # `python scripts/ingest.py --business generic_demo`
│   ├── chat.py                      # local REPL, no Telegram, for fast iteration
│   ├── eval_dialect.py              # batch-runs golden set, prints scorecard
│   └── seed_phrase_lib.py           # interactive: build Omani phrase YAML from prompts
│
├── docs/
│   ├── architecture.md
│   ├── runbook.md
│   ├── onboarding_a_business.md
│   ├── dialect_strategy.md          # deep-dive on the Omani enforcement layers
│   ├── security_model.md
│   └── adrs/
│       ├── 0001-language-and-framework.md
│       ├── 0002-llm-provider-abstraction.md
│       ├── 0003-vector-store-pgvector.md
│       ├── 0004-arabic-retrieval-strategy.md
│       ├── 0005-dialect-enforcement-layers.md
│       ├── 0006-channel-abstraction.md
│       ├── 0007-config-schema.md
│       ├── 0008-security-model.md
│       └── 0009-methodology-and-phase-gates.md
│
└── infra/
    ├── docker/
    │   ├── Dockerfile
    │   └── entrypoint.sh
    ├── postgres/
    │   └── init.sql                 # pgvector + tsvector setup
    └── grafana/
        └── dashboards/              # optional, lightweight
```

### 1.4 Data flow for one turn

1. Telegram webhook (or long-poll) → `channels/telegram.py` → normalized `ChannelMessage`.
2. `security.injection_guard` sanitizes input; `rate_limiter` checks; `pii_redactor` tags for logs.
3. `core.session` loads/creates the conversation state from Redis.
4. `memory.long_term` retrieves prior summary + relevant facts for this `chat_id`.
5. `rag.retriever` runs hybrid search over the business KB (BM25 + dense + RRF fusion).
6. `dialect.style_retriever` retrieves 2-3 best-matching Omani phrasings for the apparent intent.
7. `prompts.system_builder` assembles the final system prompt (persona + dialect rules + lexicon + few-shot + retrieved KB + retrieved style + tool schemas + safety).
8. `llm` provider generates response, possibly with tool calls.
9. If tool calls: `tools.registry` dispatches, results fed back to LLM for natural-language wrapping.
10. `dialect.validator` scores the output. If below threshold: `dialect.corrector` retries (≤2). If still bad: fall back to a canned phrase from the business phrase library.
11. `security.output_validator` enforces no system-prompt leakage, no English-default, no PII echo.
12. Reply sent via channel.
13. Throughout: `observability` logs structured events, traces spans, accumulates token cost into the session record.

---

## 2. Tech Stack & Rationale

| Concern | Chosen | Considered & rejected | Why |
|---|---|---|---|
| Language | **Python 3.11+** | TypeScript/Node, Go | Best-in-class LLM SDKs, Arabic NLP libs (PyArabic, CAMeL Tools), pgvector clients, embedding model access. |
| Packaging | **uv + pyproject.toml** | poetry, pip-tools | `uv` is fastest, modern, simple lockfile. |
| Telegram | **python-telegram-bot v21** (async) | aiogram, raw HTTP | Most mature, well-documented, async-first. |
| Web (admin/webhook) | **FastAPI** | Flask, Starlette raw | Async, Pydantic-native, OpenAPI for free. Used minimally — Telegram polling is fine for v1. |
| LLM clients | **Provider-native SDKs** behind our `LLMProvider` ABC: `google-genai`, `anthropic`, `openai` | LiteLLM, LangChain LCEL | Native SDKs give us full control of streaming, tool-call schemas, safety configs. Wrappers add magic and lag features. Our adapter is ~150 LoC per provider. |
| Vector store | **Postgres 16 + pgvector + tsvector** | Qdrant, Weaviate, Chroma, Pinecone | One DB to operate; hybrid search via tsvector+pgvector is excellent for Arabic with normalizer; trivial backup. |
| KV / session | **Redis 7** | Postgres only, KeyDB | TTL semantics, pub/sub for future voice, standard. |
| Embeddings | **`text-embedding-004` (Google, free in Gemini tier)** primary; adapters for OpenAI `text-embedding-3-large` and Cohere `embed-multilingual-v3` available behind same interface for later evaluation | jina-embeddings-v3, BGE-M3 (local) | Updated 2026-05-20: live spend cap is **$5 USD total** — Gemini's embedding model is free in user's tier and supports Arabic. Adapter pattern preserved so we can swap later without code changes. |
| ORM | **SQLAlchemy 2 (async) + Alembic** | raw psycopg, SQLModel | Mature migrations, async support, type hints. |
| Config | **Pydantic v2 + YAML** | TOML, JSON, plain dicts | Strict validation, IDE help, JSON-Schema export for editors. |
| Templating (prompts) | **Jinja2** | f-strings | Prompts get long; partial inclusion + whitespace control matter. |
| Logging | **structlog** (JSON in prod, console in dev) | stdlib only | Structured key-value logs are essential for tracing. |
| Tracing | **OpenTelemetry SDK** with optional **Langfuse** exporter | Sentry, custom | OTel is vendor-neutral; Langfuse is purpose-built for LLM traces and self-hostable. |
| Cost tracking | **Custom token-cost ledger** (per-provider price tables) | LangSmith, Helicone | We control the data; no extra account. Persisted per-conversation in Postgres. |
| Tests | **pytest, pytest-asyncio, pytest-httpx, hypothesis** | unittest | Standard. Hypothesis for normalizer edge cases. |
| Lint/format | **ruff, mypy** | black+flake8 | ruff covers both, fast. |
| Container | **Docker + Compose v2** | k8s, podman | Brief is "one-command boot"; compose is right. |
| CI | **GitHub Actions** | drone, circle | Standard; defer until repo is on GitHub. Local `make ci` mirrors what CI will run. |
| Arabic-aware tokenization | **CAMeL Tools** (`camel-tools`) for normalization + light stemming, plus a custom Omani-aware overlay | farasapy, qutuf | CAMeL is the most maintained, supports dialect tagging, and is easy to install via pip. |

**Note on Ruflo MCP plugins:** the user's CLAUDE.md mentions a `ruflo` MCP layer with `swarm_init`/`agent_spawn`/`memory_store`/etc. **These are NOT exposed in this session's deferred-tool list.** I will therefore use Claude Code's built-in `Agent` tool (with `general-purpose`, `Explore`, `Plan` subagent types) for orchestration, and `TaskCreate` for tracking. If Ruflo comes online later, we adopt it without refactoring deliverables.

---

## 3. Provider-Agnostic LLM Layer

`engine/llm/base.py` defines:

```python
class LLMProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        model: str | None = None,
        temperature: float = 0.4,
        max_tokens: int = 800,
        response_format: Literal["text", "json"] = "text",
    ) -> LLMResponse: ...

    @abstractmethod
    async def stream(self, ...) -> AsyncIterator[LLMDelta]: ...

    @property
    @abstractmethod
    def pricing(self) -> Pricing: ...   # for cost tracker
```

`LLMResponse` carries: text, tool calls (normalized to a single shape regardless of provider), usage (prompt/completion/cached tokens), finish reason, raw response (debug).

The factory reads `config.llm.provider` (`gemini` | `claude` | `openai`) and `config.llm.model`. **Switching providers = one line in config.yaml.** A `--llm-provider` CLI override lets us A/B at runtime.

**Tool-call schema normalization:** Gemini, Claude, and OpenAI all support function calling but their schemas differ. Our `normalize.py` translates a canonical `ToolSchema` (Pydantic) into each provider's native format on the way in, and translates tool-call responses back into a canonical `ToolCall` on the way out. Adapter layer eats the difference — orchestrator code is provider-blind.

**Default & only live provider for v1:** `gemini-1.5-flash` for normal turns, `gemini-1.5-pro` for the dialect evaluation runs (P4) and any quality-sensitive paths the user opts into. **Cost cap is $5 USD total** for the entire build; Gemini's free tier covers most of this. Claude and OpenAI adapters are written and exercised in unit tests with mocked HTTP, but no live API key is required for the build. They become live-tested only if/when the user provides keys.

The P4 A/B is **within the Gemini family** (Flash vs Pro) instead of across providers — Flash for cost, Pro for quality benchmarks. Cross-provider A/B is deferred until budget or keys allow.

---

## 4. Memory Architecture

### 4.1 Short-term (per conversation)

- **Storage:** Redis, keyed by `chat_id`. Stores the last N turns (N from config, default 12) plus a rolling summary string.
- **Summarization trigger:** when buffer exceeds N turns OR token estimate exceeds budget, the `summarizer.py` calls the LLM with a focused prompt to compress the oldest half into a single Arabic-language summary paragraph. Newer turns stay verbatim.
- **TTL:** 24h idle (configurable). On expiry, the next message starts fresh but long-term memory still has the summary.

### 4.2 Long-term (across conversations)

- **Storage:** Postgres table `customer_memory(chat_id, business_id, fact_text, fact_embedding, source, created_at)`.
- **Write triggers:** (a) at end of conversation, summarize and persist; (b) explicit `remember(fact)` tool call if business config enables it; (c) tool-call side-effects (e.g., `log_lead`) write structured rows.
- **Read at turn start:** top-K (default 3) facts retrieved by similarity to the current user message.

### 4.3 Privacy

- All long-term storage is per-business namespaced. Cross-business retrieval is impossible by schema.
- `pii_redactor` runs *before* persistence: phone numbers, emails, IDs are either redacted in summaries or stored in dedicated typed columns (with an explicit business consent flag in `config.yaml`).
- Right-to-delete: `python -m engine.cli forget --chat-id <id>` purges short-term and long-term rows. Documented in runbook.

---

## 5. RAG Strategy for Arabic

Arabic has high inflectional richness (root-and-pattern morphology), orthographic variants (alef forms ا/أ/إ/آ, yaa ي/ى, taa marbuta ة/ه), and optional diacritics (tashkeel). Naive embedding-only retrieval underperforms; naive BM25 misses synonyms and stems. We do **hybrid**.

### 5.1 Pipeline

1. **Ingestion** (`engine/rag/ingest.py`):
   - Walk `businesses/<name>/knowledge/`, parse markdown/txt.
   - Chunk: ~400 tokens with 60-token overlap, on heading + paragraph boundaries.
   - Per chunk, compute:
     - **Normalized text** for BM25: tashkeel removed; alef/yaa/taa variants unified; whitespace normalized; tatweel ـ stripped; lightly stemmed (CAMeL light stemmer).
     - **Original text** preserved for display.
     - **Embedding** of the original (multilingual model handles morphology).
   - Store in `kb_chunk(business_id, chunk_id, original, normalized, tsvector_ar, embedding, source_file, heading_path)`.
   - tsvector built with custom `arabic_simple` dictionary (we ship the config in `infra/postgres/init.sql`).

2. **Retrieval** (`engine/rag/retriever.py`):
   - Normalize the query the same way.
   - **Lexical:** `ts_rank` over `tsvector_ar` (BM25-like, configurable weights for heading vs. body).
   - **Dense:** cosine similarity over `embedding`.
   - **Fusion:** Reciprocal Rank Fusion (RRF) with k=60. Take top-8.
   - **Optional rerank:** Cohere rerank-multilingual-v3 over top-8 → top-3 (gated by `config.rag.rerank: true`; default off to save cost in dev).

3. **Style retrieval** (`engine/dialect/style_retriever.py`):
   - Separate, smaller index over phrase library (`businesses/*/phrases/*.yaml`).
   - At retrieval, classify the user's intent (greeting / question / objection / etc.) using a tiny LLM call OR keyword heuristics (configurable); fetch best 2-3 phrasings tagged with that intent.
   - These are injected into the prompt as "preferred phrasing examples" — *grounding the model in Omani register, not just lexicon*.

### 5.2 Why this works for Arabic specifically

- Normalization handles the morphological-orthographic variation that breaks naive search.
- BM25 catches exact terms (names, hours, prices) where embeddings often miss.
- Dense catches paraphrase ("متى تفتحون؟" vs. "ساعات العمل").
- RRF avoids tuning a magic weight.
- Style retrieval is the key innovation — most Arabic chatbots fail dialect because they generate freely; we *retrieve a tone reference* and tell the model to match it.

---

## 6. Omani Dialect Strategy — The Heart of the System

> **This is the section the brief explicitly called out as hardest. I am giving it the most space because it deserves it.**

### 6.1 The problem, named precisely

LLMs default to **Modern Standard Arabic (MSA / Fusha)** when generating Arabic. Even when prompted for "Omani dialect," they routinely produce:

- MSA grammar with sprinkled Omani vocabulary → sounds bookish, not native.
- Mixed dialects: Egyptian (`إزاي`, `عايز`), Levantine (`شو بدك`), Saudi/Yemeni (`إيش`) — leak in because Omani training data is thin.
- Over-formal register: full iʿrāb endings, complex relative clauses, dual forms (مثنى) that no Omani says aloud.
- Wrong particles: `نعم` instead of `إيه/هاء`, `أين` instead of `وين`, `ماذا` instead of `شو/إيش`, `الآن` instead of `الحين`, `كيف حالك` instead of `شخبارك`.

A receptionist that talks like a news anchor or like a Cairo taxi driver loses trust instantly. Customer-facing means **one wrong-dialect reply can sink the business**.

### 6.2 Seven-layer defense

| # | Layer | What it does | Where it lives | Cost |
|---|---|---|---|---|
| 1 | **Prompt-time lexicon table** | System prompt includes a compact MSA→Omani mapping table for the most-confused particles and verbs | `prompts/templates/lexicon_table.j2` | 0 (in prompt) |
| 2 | **Phrase library few-shot** | 6-10 curated Omani exchanges injected as few-shot, rotated by intent | `prompts/templates/few_shot.j2` + `businesses/*/examples/conversations.yaml` | 0 (in prompt) |
| 3 | **Style retrieval (RAG-for-tone)** | At runtime, retrieve 2-3 phrasings tagged with the detected intent and inject them as "preferred phrasings" | `dialect/style_retriever.py` + `businesses/*/phrases/*.yaml` | 1 extra retrieval per turn |
| 4 | **Rules-based validator** | Scans output for banned MSA tokens, non-Omani dialect markers, formality flags. Weighted score; below threshold → re-prompt | `dialect/validator.py` + `dialect/lexicon.py` | ~0 (regex / set lookup) |
| 5 | **LLM-as-judge (sparingly)** | On borderline scores, secondary call: "Rate this for Omani-ness 1-5, explain." Used for offline eval and CI; gated for live use behind `config.dialect.use_judge: true` | `dialect/validator.py` | 1 small LLM call (only when triggered) |
| 6 | **Correction loop** | If validator fails, retry the generation with: stricter system prompt, the failed output as a "do not say this" anti-example, the validator's specific complaints. Max 2 retries; then fall back to canned phrase from phrase library | `dialect/corrector.py` | up to 2 extra LLM calls (rare) |
| 7 | **Golden CI tests + human review queue** | 40+ canonical user inputs with expected-pattern regex of acceptable Omani responses. CI fails if pass rate drops. Flagged-low outputs route to a review folder for native-speaker spot-checks | `tests/dialect/`, `engine/observability/review_queue.py` | ~0 in-line; human time offline |

### 6.2.5 Regional consistency and register

Oman has **distinct regional varieties**: Muscat / coastal (Sahili), interior (Sharqia / Dakhliya), Dhofari (Salalah and south), Musandam (north). Mixing them sounds *worse* than picking one and sticking — listeners hear it as an outsider faking the accent.

**Decision (2026-05-20, per user direction):**
- **Pick one region: Muscat / coastal Sahili Omani** as the default for `generic_demo`. Rationale: it is the *national lingua franca* — what one hears on Oman TV news interludes, in Muscat government offices, in customer-service contexts across the country. Speakers from interior / Dhofar understand it readily; the reverse is not always true. (Per-business override is available via `dialect.region: muscat | interior | dhofari | musandam` — but the default and only fully-seeded library is Muscat.)
- **Register: official-respectful, not chat-casual.** A receptionist speaks like a polite professional, not a friend at a majlis. We avoid: street slang (e.g., `يلا`, casual interjections), playful filler, overly familiar address.
- **Address: respectful default.** Use plural-of-respect forms (`حياكم`, `تفضلوا`, `كيف اقدر اخدمكم`) when address is uncertain; switch to singular only after the customer has set a casual tone.
- **The user's 4 corrections (ويش / ايوا / كيف الحال / كيف اقدر اخدمك) are register-compatible** — they are Omani vocabulary used in respectful service contexts, not slang. They stay.
- **Drop or downgrade chat-style entries** in the AI-drafted lexicon: `هلا` (kept but tagged `register: casual`, not used by default), `وايد` (kept but tagged `register: casual`), `زين` (replaced with `ممتاز` / `طيب` for service contexts), playful close phrases (replaced with `تحت أمركم` / `في خدمتكم`).

This regional + register decision is encoded as defaults in `engine/dialect/lexicon.py` and `businesses/generic_demo/phrases/*.yaml`. Per-business override is one config knob.

### 6.3 The lexicon table (preview — fuller version in `dialect/lexicon.py`)

> **Living document.** This table is iteratively corrected by the project's native-speaker reviewer (Basil). Entries marked ✅ are user-confirmed corrections received during planning on 2026-05-20. Unmarked entries are AI-drafted and pending validation during the post-implementation teaching session (§6.9). On any uncertainty, the bot defers to the user's verdict and we update the lexicon — no engineer in the loop.
>
> **Region: Muscat / coastal Sahili Omani. Register: official-respectful.** Casual-only forms are tagged and not used by the default receptionist persona.

| MSA / English | Omani | Notes |
|---|---|---|
| ماذا / "what" | **ويش** ✅ | user-confirmed; **شو / إيش rejected** (added to banned-tokens list) |
| نعم / "yes" | **ايوا** ✅ | user-confirmed; **إيه / هاء rejected** (added to banned-tokens list) |
| "how are you" | **كيف الحال** ✅ | single canonical Omani form; **كيف (alone) / شخبارك dropped** per user |
| "how can I help you" (service register) | **كيف اقدر اخدمك** ✅ | service-oriented form; **شو تبي / شو تبغى rejected** per user — appropriate for a receptionist who is *serving*, not interrogating |
| أين | وين | "where" |
| الآن | الحين | "now" |
| لا | لا (same) | — |
| لماذا | ليش | "why" |
| متى | متى (same in Omani) | — |
| كثير | كثير / وايد (casual only) | "a lot/very" — prefer `كثير` in official register |
| جيد | ممتاز / طيب | "good" — `زين` tagged casual; not used by default |
| لا بأس | ما في مشكلة / تكفون لا تشلون هم | "no problem" — respectful forms |
| مرحبا | حياكم الله / مرحبا / تفضلوا | greetings; plural-of-respect default; `هلا` tagged casual |
| من فضلك | لو سمحت / إذا ممكن | "please" — **لو تكرم rejected by user 2026-05-20** (banned-token) |
| شكرا | مشكورين / يعطيكم العافية | "thanks" — plural-of-respect; `يعطيكم العافية` high register |
| (you're welcome) | العفو / تحت أمركم | service-context closes |
| (at your service) | في خدمتكم / تحت أمركم | signature respect-phrases |

This table is loaded once at startup, validated at startup (it's also used by the validator), and rendered into the system prompt. The ✅ corrections also seed `dialect/banned_tokens.yaml` so the validator catches regressions.

### 6.4 The banned-tokens list (validator input)

The validator scores `−w` per occurrence of a banned token (after normalization to handle alef/yaa variants). Banned by default:

- **MSA particles in dialogue:** `ماذا`, `أين`, `الآن`, `إذًا`, `حيث`, `إن`, `أنّ`, `كي`, `بيد أن`, `بل`, `سوف` (the bare form, not `راح/ب-`)
- **Egyptian markers:** `إزاي`, `عايز`, `بتاع`, `دلوقتي`, `كده`, `ليه كده`, `يلا`
- **Levantine markers:** `شو بدك`, `هلق`, `كتير`, `منيح`, `بس` (when used as "but" not as "enough")
- **Iraqi/Saudi-only markers:** `شلون`, `وش`, `هسه`
- **Formality flags:** dual-form endings (`ـان`, `ـين` outside common words), full nominative/accusative diacritics in casual reply

Scores roll up to a 0-100 "Omani index". Threshold default: 70. Below → retry. Above 90 → no judge call. 70-90 → optionally trigger judge if `use_judge: true`.

### 6.5 The phrase library structure

```yaml
# businesses/generic_demo/phrases/greetings.yaml
- intent: opening_greeting
  variants:
    - "هلا والله، حياك الله. كيف أقدر أساعدك اليوم؟"
    - "أهلين، حياك. تفضل، شو تحتاج؟"
    - "مرحبا، نورت. أنا في خدمتك."
  context: "Use for first message from a new user or after long idle"
  formality: medium

- intent: returning_user_greeting
  variants:
    - "حياك مرة ثانية. كيف نقدر نساعدك؟"
  context: "Use when chat_id has prior history within 24h"
  formality: medium
```

Same structure for `apologies`, `confirmations`, `clarifications`, `farewells`, `small_talk`, `escalations`. **Adding more variety = editing YAML, no code change.**

### 6.6 Honesty about limitations (UPDATED — native reviewer secured)

**Update 2026-05-20:** The project lead (Basil) is acting as the in-loop native-speaker reviewer. He has already corrected the initial lexicon during planning (4 entries → §6.3) and has committed to a live teaching session post-implementation (§6.9). This **materially reduces R1** (dialect drift) from "Critical, High-likelihood" to "Critical, Medium-likelihood."

Remaining honest caveats:

1. The initial phrase libraries we ship in `businesses/generic_demo/phrases/` will be AI-drafted-then-corrected, not native-authored from scratch. We surface every variant in YAML so the user can rewrite freely.
2. Even with a reviewer in the loop, dialect quality is a **moving target** — what passes today may regress when a model changes. The golden CI test (§6.7) and live correction loop (§6.9) together form the durable safety net.
3. We do **not** yet have multiple Omani reviewers, so a single reviewer's preferences may not represent every Omani's expectations. Documented as an open caveat in `docs/dialect_strategy.md` — businesses can layer their own preferred phrasings per dialect sub-region (Muscat vs. Dhofari vs. interior) via per-business phrase libraries.

This is the part I cannot fake with cleverness. I am surfacing it now rather than later.

### 6.7 Offline evaluation harness

`scripts/eval_dialect.py` runs the golden conversations under each configured provider/model and produces a CSV: `case_id, provider, model, generated, omani_index, judge_score, pass`. We track this over time to catch regressions when prompts or models change.

### 6.8 Response register and length adaptation

A native-sounding receptionist matches the **weight** of the customer's message. A one-word `مرحبا` deserves a one-line reply, not a paragraph. A detailed question warrants a detailed answer. We enforce this with:

- **System-prompt rule** (in `persona.j2`): *"طابق طول ردك مع حجم سؤال الزبون. اذا الرسالة قصيرة، ردك قصير. اذا السؤال مفصل، رد بتفصيل مناسب. الأصل: الإيجاز."* (Match your reply length to the customer's message weight. Short → short. Detailed → matching detail. Default: brevity.)
- **Per-business config knob** in `business.persona.response_style` (see §10) — soft cap for casual turns, hard cap for detailed answers.
- **Post-generation length check**: if `len(user_message.split()) <= 6` AND `len(reply.split()) > 40`, regenerate once with a stricter brevity instruction. If still over, ship as-is (we don't infinitely retry).
- **Golden tests** include short-input/short-output pairs to catch over-explanation regressions (e.g., `"مرحبا"` should not trigger a 5-line reply).
- **Greetings & small talk** are explicitly tagged in the phrase library with target length so the style retriever surfaces appropriately-sized phrasings.

### 6.9 Live correction loop (teaching session)

After implementation completes (gate of P7), the user runs a simulated conversation with the bot and corrects it in real time. The system supports this natively:

- **Privileged `/teach` command** — only the configured `admin_chat_ids` can use it. Reply to a bot turn with `/teach <correction>` to flag and supply the right phrasing.
- **Storage:** each correction creates a `dialect_correction(input_text, wrong_output, corrected_output, reason, intent_guess, applied_at, applied_by)` row in Postgres.
- **Apply-corrections script** (`scripts/apply_corrections.py`) — run by the user on demand:
  1. Adds the rejected tokens/phrases to `dialect/banned_tokens.yaml` with comment `# corrected by user on YYYY-MM-DD`.
  2. Adds the corrected phrasing as a new variant in the matching `businesses/<biz>/phrases/<intent>.yaml`.
  3. Optionally adds the `(input, corrected_output)` pair to `businesses/<biz>/examples/conversations.yaml`.
  4. Re-runs `scripts/eval_dialect.py` and prints the new scorecard.
- **Outcome:** the user's live corrections become **durable, code-reviewable improvements with no engineer in the loop**. This is the highest-leverage feature in the system because it converts dialect mistakes into permanent regression tests.

This loop is mandatory before any rollout to real customers. It is *also* available continuously in production — businesses with their own dialect reviewers can run their own teaching sessions.

---

## 7. Function Calling / Tools

### 7.1 Interface

```python
class Tool(ABC):
    name: str
    description: str                 # in Arabic, since LLM sees it
    input_schema: dict               # JSON-Schema
    output_schema: dict
    requires_consent: bool = False   # if True, bot asks user before invoking
    side_effects: bool = True        # for safety logging

    @abstractmethod
    async def execute(self, args: dict, ctx: ToolContext) -> dict: ...
```

### 7.2 Built-in tools (engine ships them)

- `escalate_to_human(reason, summary)` — drops a notification into a configured channel (Telegram chat, webhook URL); replies a polite Omani holding message.
- `log_lead(name?, phone?, intent, notes)` — writes to `leads` Postgres table.
- `check_business_hours()` — returns current open/closed status from `config.yaml.hours`.
- `handoff_message(to, message)` — for businesses with multiple departments.
- `remember(fact)` — explicit long-term memory write (gated by business config).

### 7.3 Business-specific tools

Defined in `businesses/<name>/tools.yaml`:

```yaml
tools:
  - name: book_appointment
    description: "احجز موعد للزبون. لازم تسأل عن الاسم والوقت قبل ما تنادي هذي الأداة."
    input_schema:
      type: object
      properties:
        customer_name: { type: string }
        service: { type: string, enum: ["consultation", "follow_up"] }
        date_time_iso: { type: string, format: "date-time" }
      required: [customer_name, service, date_time_iso]
    handler:
      type: http
      method: POST
      url: "${BOOKING_API_URL}/appointments"
      headers: { Authorization: "Bearer ${BOOKING_API_TOKEN}" }
    # OR
    handler:
      type: stub
      response: { confirmation_id: "DEMO-12345", status: "confirmed" }
```

For v1 demo, all business tools are `stub` handlers. The `http` handler is implemented and tested but no live endpoints are configured — that's a per-business onboarding step.

### 7.4 Safety

- Tool descriptions and schemas are validated at startup.
- Tools with `requires_consent: true` make the orchestrator force a confirmation turn before execution.
- All tool calls and results logged with `pii_redactor` applied.
- A tool that fails returns a structured error that the LLM is instructed (in system prompt) to render as a natural Omani apology and offer escalation.

---

## 8. Security & Safety

| Threat | Mitigation | Where |
|---|---|---|
| Prompt injection via user input | Input sanitizer strips/escapes role-impersonation phrases ("ignore previous", "system:", "you are now"); injection-attempt patterns logged | `security/injection_guard.py` |
| Prompt injection via business KB | At ingest time, detect and reject suspicious patterns; KB content is rendered with clear delimiters in the prompt; output validator checks for system-prompt leakage | `rag/ingest.py`, `security/output_validator.py` |
| PII leakage (logs) | Regex + libphonenumber + email regex; redact before any log/trace sink | `security/pii_redactor.py` |
| PII leakage (responses) | Output validator scans for PII in replies that the user didn't already share | `security/output_validator.py` |
| Rate abuse | Token bucket per `chat_id` and per-business global; configurable burst/sustain; reply with Omani apology when limited | `security/rate_limiter.py` |
| Cost runaway | Per-conversation max tokens; per-business daily cap; cost tracker emits alert at 80% of cap | `observability/cost_tracker.py` |
| Secret exposure | All secrets via env vars; `.env.example` committed, `.env` gitignored; no secrets in business YAML (only `${ENV_VAR}` references) | `config/loader.py` |
| Off-topic / jailbreak | System prompt explicitly scopes role; refusal templates in Omani for out-of-scope; escalation tool for genuinely off-topic | `prompts/templates/safety_rules.j2` |
| Language hijack (user tries to flip to English) | Detection + Omani redirection; configurable per-business (some businesses want bilingual) | `security/output_validator.py` (language detect via fastText langid) |
| Persistence of sensitive long-term facts | Long-term writes filtered by `pii_redactor`; phone/email stored only in typed columns gated by business consent flag | `memory/long_term.py` |

---

## 9. Observability & Cost Tracking

- **Logging:** structlog. Every turn emits: `turn_id`, `chat_id` (hashed in prod), `business_id`, `provider`, `model`, durations per stage, retrieval hit count, dialect score, tool calls, token usage, USD cost.
- **Tracing:** OpenTelemetry spans for: `turn`, `retrieve`, `style_retrieve`, `prompt_build`, `llm_call`, `tool_call`, `validate`, `correct`. Optional Langfuse exporter (self-hosted) for LLM-specific timeline views.
- **Metrics:** Prometheus-style counters (turns, errors, validator failures, tool calls, escalations). Exposed on `/metrics` from a tiny FastAPI surface.
- **Cost tracker:** Per-call ledger row `cost_event(turn_id, provider, model, in_tokens, out_tokens, cached_tokens, usd)`. Daily roll-up view per business. Configurable price tables in `infra/prices.yaml` (so prices update without code change).
- **Dashboards:** Minimal Grafana JSON in `infra/grafana/dashboards/`. Optional — only used if user runs Grafana via compose.

---

## 10. Configuration Schema (the business contract)

`businesses/<name>/config.yaml`:

```yaml
business:
  id: generic_demo
  display_name: "شركة الواحة للخدمات"
  industry: "general_services"
  language: ar-OM             # locked; enforced by dialect layer
  timezone: Asia/Muscat
  contact:
    phone: "+968 24 000 000"
    email: "info@example.om"
    address: "مسقط، عمان"
  hours:
    monday:    [{ open: "08:00", close: "17:00" }]
    # ... per day
    friday:    []             # closed
    saturday:  [{ open: "08:00", close: "13:00" }]

persona:
  name: "سارة"
  role: "موظفة استقبال"
  voice: "محترمة، رسمية، خدومة، صبورة، واضحة"   # respectful, official, helpful, patient, clear
  formality: high                # [low|medium|high] — receptionist defaults to high
  region: muscat                 # [muscat|interior|dhofari|musandam] — Muscat = Sahili default
  address: plural_respect_default # use plural-of-respect (حياكم، تفضلوا) by default; downshift to singular only after customer sets casual tone
  response_style:
    length: adaptive             # short user → short reply; detailed user → detailed reply
    max_words_casual: 40         # soft cap for greetings, small talk, simple confirmations
    max_words_detailed: 150      # hard cap even for complex answers
    one_question_per_turn: true  # don't stack multiple questions in one reply
  signature_close: "تحت أمركم، أي خدمة ثانية؟"  # respectful close; subject to user review

llm:
  provider: gemini             # gemini | claude | openai
  model: gemini-1.5-flash
  temperature: 0.4
  max_tokens: 800
  fallback_provider: claude    # if primary fails
  fallback_model: claude-sonnet-4-6

embedding:
  provider: openai
  model: text-embedding-3-large

rag:
  top_k: 5
  rerank: false
  chunk_size_tokens: 400
  chunk_overlap_tokens: 60

dialect:
  enforce: true
  threshold: 70
  use_judge: false
  max_corrections: 2
  banned_token_extras: []      # business can add to default list

memory:
  short_term_turns: 12
  long_term_enabled: true
  summarize_after_turns: 16

tools_file: tools.yaml
phrase_dir: phrases/
examples_file: examples/conversations.yaml
knowledge_dir: knowledge/

channels:
  telegram:
    enabled: true
    bot_token_env: TELEGRAM_BOT_TOKEN
    allowed_chat_ids: []       # empty = all; restrict for prod
    escalation_chat_id_env: TELEGRAM_ESCALATION_CHAT_ID

security:
  rate_limit:
    per_chat_burst: 5
    per_chat_sustained_per_min: 20
    per_business_daily_token_cap: 5_000_000
  pii_consent: false           # if true, can persist phone/email in typed columns
  allow_languages: ["ar"]      # bot refuses to switch to other languages

observability:
  log_level: INFO
  trace_exporter: none         # none | otlp | langfuse
```

The schema is enforced by Pydantic v2 at startup. Mismatch → process exits with a clear error pointing to the offending line. JSON Schema is exported to `docs/schemas/business_config.schema.json` for editor support.

---

## 11. Telegram Adapter & Future Voice

`engine/channels/base.py`:

```python
class Channel(ABC):
    @abstractmethod
    async def start(self) -> None: ...
    @abstractmethod
    async def send(self, chat_id: str, content: ChannelMessage) -> None: ...
    @abstractmethod
    def on_message(self, handler: Callable[[ChannelMessage], Awaitable[None]]): ...
```

`ChannelMessage` carries `text`, `attachments`, `metadata`. Voice integration (later) implements the same interface, with attachments holding audio blobs and the orchestrator orchestrating STT before and TTS after — zero engine changes.

Telegram adapter uses `python-telegram-bot` long-polling in dev (no webhook setup needed). Webhook mode is implemented and gated by `channels.telegram.mode: webhook` for prod.

---

## 12. Agent Roster

> **Reminder:** Ruflo swarm tools are not connected. We use Claude Code's native `Agent` tool with `general-purpose`, `Explore`, and `Plan` subagent types, launched in parallel within phases. The "roster" below is a *logical* roster — each role maps to a sub-agent invocation with a tightly scoped prompt and deliverable.

| Role | Why this role exists | Subagent type | Activates in phases |
|---|---|---|---|
| **Foundation Engineer** | Repo skeleton, pyproject, docker-compose, config loader, CI. Everything else builds on this. | general-purpose | P0 |
| **LLM Adapter Engineer** | The provider abstraction is core; one engineer focused on it produces the cleanest interface | general-purpose | P1 |
| **RAG Engineer** | Arabic-aware retrieval is a specialist concern (normalization, hybrid, RRF, reranker) | general-purpose | P2 |
| **Telegram Channel Engineer** | Channel abstraction + Telegram adapter; needs to be done right so voice is a drop-in later | general-purpose | P1 |
| **Memory Engineer** | Short-term + summarization + long-term; touches Redis, Postgres, summarizer prompts | general-purpose | P2 |
| **Tools/Function-Calling Engineer** | Tool ABC, registry, schema normalization across providers, builtins | general-purpose | P3 |
| **Dialect Engineer** | The Omani enforcement subsystem. This is the **most senior specialist role**; gets its own phase | general-purpose | P4 |
| **Security Engineer** | Injection guard, PII redactor, rate limiter, output validator, red-team suite | general-purpose | P5 |
| **Observability Engineer** | structlog setup, OTel spans, cost ledger, optional Langfuse | general-purpose | P6 |
| **QA / Test Engineer** | Pytest infrastructure + golden dialect tests + e2e harness | general-purpose | P0 (scaffolding), then continuously |
| **Docs & ADR Scribe** | Architecture doc, runbook, onboarding guide, ADRs as decisions are made | general-purpose | every phase, finalizing in P7 |
| **Explorer** | Used ad-hoc when a phase requires research (e.g., "best pgvector arabic config") | Explore | as needed |
| **Architect** | Used ad-hoc when a non-trivial design decision arises mid-implementation | Plan | as needed |

**Parallelization rule:** within a phase, agents whose deliverables don't depend on each other are launched in a **single message with multiple Agent tool blocks** (true parallel). Sequential dependencies are honored.

**Coordination:** I (the lead agent) hold the source of truth in:
- this PLAN.md (architecture, scope)
- `TaskCreate`/`TaskList` for live status
- ADR files for ratified decisions
- A `STATE.md` at repo root that I keep updated with current phase, blockers, decisions log

I read subagent results, integrate them, run end-of-phase verification myself, and produce the phase report.

---

## 13. Methodology & Phase Gates

**SPARC-flavored, demo-gated.** Every phase ends with a runnable demo and a written phase report (`docs/phase_reports/phase_<n>.md`). No phase advances until its gate is green.

### Phase P0 — Foundation & Conventions
- Repo skeleton (folders, pyproject, .env.example, .gitignore, .dockerignore)
- Docker Compose with Postgres+pgvector, Redis, app stub
- Config loader (Pydantic v2) reads `businesses/generic_demo/config.yaml` and validates
- structlog configured
- pytest scaffolding green on a trivial test
- ADR-0001 (language/framework), ADR-0007 (config schema), ADR-0009 (methodology)
- **Gate:** `docker-compose up` clean; `python -m engine.cli health` exits 0; `pytest` exits 0; lint+mypy clean

### Phase P1 — LLM Adapter & Chat Loop
- `LLMProvider` ABC + Gemini, Claude, OpenAI adapters
- Provider factory wired to config
- Telegram channel adapter (long-polling)
- Orchestrator skeleton: receive message → call LLM with bare system prompt → reply
- Capture user's `chat_id` on `/start`, log it
- ADR-0002 (LLM abstraction), ADR-0006 (channel abstraction)
- **Gate:** `/start` on Telegram returns an Omani greeting via Gemini; same works with `LLM_PROVIDER=claude` and `LLM_PROVIDER=openai` env override (Claude/OpenAI keys placeholders if not provided — graceful skip)

### Phase P2 — Memory & RAG
- Redis short-term buffer; rolling summarizer
- Postgres `kb_chunk` + ingest script
- Arabic normalizer (CAMeL Tools + custom overlay)
- Hybrid retriever (BM25 via tsvector + dense via pgvector + RRF)
- Long-term memory table + retrieval
- ADR-0003 (pgvector), ADR-0004 (arabic retrieval)
- **Gate:** bot answers ≥5 questions from `generic_demo` KB correctly in Omani Arabic; memory persists across two messages in one conversation

### Phase P3 — Function Calling & Tools
- Tool ABC, registry, schema normalization across providers
- Builtin tools (`escalate_to_human`, `log_lead`, `check_business_hours`)
- One business-specific stubbed tool: `book_appointment`
- Tool descriptions in Arabic, schemas in JSON-Schema
- **Gate:** bot books a fake appointment (calls stub, gets confirmation ID, replies naturally)

### Phase P4 — Omani Dialect Enforcement *(the big one)*
- Lexicon module (Muscat / Sahili region, official-respectful register) + banned-tokens list (seeded with user's 4 corrections + rejected forms)
- Phrase library YAML (`businesses/generic_demo/phrases/*.yaml`) + style retriever
- Few-shot loader + prompt template
- Rules-based validator (includes region-tag + register-tag enforcement)
- LLM-as-judge (gated; Gemini Pro)
- Correction loop
- Golden conversation set (40+ canonical turns curated)
- `/teach` Telegram command + `scripts/apply_corrections.py` for live user-driven updates (§6.9)
- `eval_dialect.py` produces a scorecard CSV
- ADR-0005 (dialect strategy)
- **Gate:** golden set passes at ≥90% on `gemini-1.5-flash`; scorecard CSV committed; A/B report **(Flash vs Pro within Gemini family)** committed to `docs/dialect_strategy.md`; `/teach` command demonstrably extends the lexicon and phrase library end-to-end

### Phase P5 — Security & Safety
- Injection guard (input + KB ingest)
- PII redactor (logs + responses + persistence)
- Rate limiter
- Output validator (no system-prompt leak, language lock, PII echo guard)
- Red-team test suite (50+ adversarial prompts)
- ADR-0008 (security model)
- **Gate:** red-team suite passes 100%; PII never appears in logs in suite run

### Phase P6 — Observability & Cost
- structlog JSON + console modes
- OpenTelemetry spans on all major boundaries
- Cost tracker ledger + per-conversation summary
- `/metrics` endpoint
- Optional Grafana dashboards
- **Gate:** one full demo conversation produces complete trace + cost report (in `docs/phase_reports/phase_6.md`)

### Phase P7 — Demo Business, Docs & Onboarding
- `generic_demo` populated with realistic KB (10+ docs), phrase library (7 intent files, 5+ variants each), examples (15+ turns), tools (5+ defs)
- All ADRs finalized
- `docs/architecture.md`, `docs/runbook.md`, `docs/onboarding_a_business.md`, `docs/dialect_strategy.md`, `docs/security_model.md`
- README quickstart
- **Final gate:** a fresh developer can clone the repo, follow `onboarding_a_business.md`, and add a second dummy business in <30 minutes — verified by me running through the steps and timing it

### Inter-phase reports

After every phase: a `docs/phase_reports/phase_<n>.md` containing what was built, what changed since plan, decisions made, risks surfaced, demo recording/transcript, and the gate-verification evidence. (I am interpreting the truncated "After each phase, produce…" in your message as this — please confirm or correct.)

---

## 14. Testing Strategy

| Layer | What we test | How | Target |
|---|---|---|---|
| Unit | Pure functions: normalizer, validator scoring, lexicon lookups, schema normalization, redactor | pytest, hypothesis for edge cases | >90% coverage of these modules |
| Adapter | LLM adapters with mocked HTTP (pytest-httpx) | Verify request shape, response parsing, tool-call normalization | 100% of adapter methods |
| Integration | RAG pipeline against real pgvector with seeded fixtures; tool execution with stub handlers; memory round-trip | pytest with docker-compose-managed services | Critical paths only |
| Dialect Golden | 40+ canonical (input, expected-pattern) pairs run through full pipeline | `tests/dialect/test_golden.py` | ≥90% pass rate |
| Red-team | Adversarial inputs: injection, PII probe, role-flip, language-flip, jailbreak, off-topic | `tests/security/` | 100% pass |
| End-to-end | Simulated Telegram conversation, mocked Telegram API or test mode | `tests/e2e/` | Smoke only — happy path + 2 failure modes |
| Manual | Real Telegram chat with the bot at end of each phase | Recorded transcripts in phase reports | Sign-off by you |

**Coverage targets:** engine modules ≥85% line coverage. Business config code paths ≥70% (lots of YAML-driven branches). Adapters 100% method coverage.

---

## 15. Risks & Mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Dialect drift in production (sounds MSA-ish or wrong-dialect) | Medium (was High) | **Critical** | Seven-layer defense (§6); **native-speaker reviewer (Basil) actively in loop — already corrected 4 lexicon entries during planning, will run live teaching session (§6.9) post-implementation**; golden CI tests as regression net |
| R2 | Gemini free-tier rate limits / $5 spend cap during dev | Medium | Medium | Aggressive prompt-cache reuse; Flash for normal turns, Pro only for evaluation; mocked HTTP in tests; **spend tracker emits warning at $3, hard-stop at $5**; user holds the only live API key so we can't accidentally over-spend without his action |
| R3 | Arabic normalization edge cases (orthographic variants we miss) | Medium | Medium | Dedicated normalizer module; hypothesis fuzz tests; CAMeL Tools as baseline |
| R4 | Function-calling schema differences across providers cause silent failures | Medium | High | Adapter-level normalization with assertion tests on every provider; contract tests |
| R5 | PII leakage in logs or replies | Low | **Critical** | Redactor at every sink; red-team includes PII probe; periodic log audit script |
| R6 | Prompt injection via knowledge-base content | Low (we control KB) | High | Ingest-time sanitization; clear KB delimiters in prompt; output validator |
| R7 | Cost runaway from long contexts + RAG | Medium | Medium | Token budget per turn; per-business daily cap with alert; rolling summarization; cached RAG context where possible |
| R8 | Latency: chain of retrieve→generate→validate→maybe-correct is slow | Medium | Medium | Parallelize where possible (RAG and style-retrieve can fan out); validator is rules-first (cheap); judge only on suspicion; p95 target 6s |
| R9 | Ruflo MCP layer not available (re: CLAUDE.md) | Confirmed | Low | Use Claude Code's native `Agent`/`TaskCreate`. Document where Ruflo would have plugged in for future adoption |
| R10 | Telegram `getUpdates` empty — chat ID undiscovered | Confirmed | Low | Capture chat_id on first `/start` during P1; user re-sends if needed |
| R11 | Embedding model price (text-embedding-3-large is paid) | Mitigated | — | **Resolved 2026-05-20:** default switched to Google `text-embedding-004` (free in Gemini tier). OpenAI/Cohere adapters preserved for later. |
| R12 | Knowledge base goes stale per business | Continuous | Medium | Re-ingest CLI is one command; `last_ingested_at` per business surfaced in `/metrics`; runbook documents cadence |
| R13 | Bot escalates everything or escalates nothing | Medium | Medium | Escalation tool description + system-prompt rules tuned in P4; golden tests cover "should escalate" and "should NOT escalate" cases |
| R14 | Single-tenant scaling not addressed (multiple businesses on one deployment) | Low (v1 scope) | Low | Architecture supports it (business_id everywhere); deferred until v2; documented |

---

## 16. Acceptance Criteria for "Done"

Implementation is complete when **all** of these are demonstrably true:

1. **One-command boot:** `docker-compose up` on a fresh machine brings up Postgres+pgvector, Redis, and the app; `python -m engine.cli health` exits 0.
2. **Provider-agnostic LLM proven:** the demo bot answers via Gemini by default; switching `llm.provider` to `claude` then `openai` in `config.yaml` (and providing the respective API key) works with zero code changes. Verified manually + by adapter contract tests.
3. **Telegram round-trip:** sending any of 10 representative customer questions to `@techmate_reception_bot` produces correct, in-character, Omani-Arabic replies grounded in the `generic_demo` knowledge base.
4. **Function calling proven:** at least one tool (`book_appointment` stub) is invoked end-to-end and the bot wraps the result naturally in Omani.
5. **Dialect quality gate:** golden conversation set (≥40 turns) passes at **≥90% under the rules-based validator** on Gemini default. Scorecard CSV committed. A/B comparison across providers committed.
6. **Memory works:** the bot remembers what was said earlier in the conversation; long-term memory recalls a fact from a prior session (demonstrable in a recorded two-session test).
7. **Security gate:** red-team suite (50+ adversarial prompts) passes 100%. No PII appears in any log line during the suite run. Rate limits trigger correctly.
8. **Observability gate:** for any conversation, a structured log stream + OTel trace + cost ledger row exist. One sample conversation report is in `docs/phase_reports/phase_6.md`.
9. **Cost report:** per-conversation USD cost is computable and accurate within 5% of provider-reported usage. **Total cumulative spend across the entire build ≤ $5 USD** (hard cap). Phase reports include running cost-to-date.
10. **Latency gate:** p95 end-to-end turn latency <6 seconds on the dev machine for a RAG-grounded turn.
11. **Onboarding gate:** following `docs/onboarding_a_business.md`, a developer adds a second dummy business in <30 minutes without engine code edits. **I verify this myself before declaring done.**
12. **All 9 ADRs written** and committed.
13. **All phase reports** (P0–P7) committed under `docs/phase_reports/`.
14. **Native-speaker review is acknowledged as a separate, mandatory gate before any real customer rollout.** Documented explicitly in `docs/runbook.md`. Not part of code "done" but part of "ship to customers" — distinction is explicit.

---

## 17. Assumptions

1. **Python 3.11+** is acceptable on dev and prod targets.
2. **Docker Desktop on Windows host** works for one-command boot (per environment).
3. **Postgres 16 + pgvector** is acceptable (pulled via docker-compose).
4. **Gemini default for dev** is acceptable; Claude and OpenAI keys are optional during dev.
5. **No live customer rollout** happens during this build — we deliver the scaffold + demo business; you handle commercial integration separately.
6. **No native Omani speaker** is available during the build; we acknowledge this gap explicitly and gate live rollout on it.
7. **Voice (STT/TTS) is out of v1 scope** but architecturally allowed.
8. **No Omani PDPL / regulatory compliance audit** is in scope — we design with sensible defaults (per-business isolation, redaction, right-to-delete) but do not certify.
9. **GitHub Actions CI is deferred** — we will produce a `Makefile` / `tasks.toml` so CI is a one-line addition when the repo lands on GitHub.
10. **The `generic_demo` business is a generic small-services company** (think: a small services firm with appointments, hours, FAQs, escalations). Confirmed by user 2026-05-20.
11. **Gemini is the only live LLM provider for v1.** Claude/OpenAI adapters are written and unit-tested but no live key is required. **Cost cap $5 USD** total. Confirmed by user 2026-05-20.
12. **Region pinned to Muscat / Sahili Omani; register: official-respectful.** Confirmed by user 2026-05-20.
13. **Git + GitHub collaboration is required.** Two-developer flow (Basil + friend), feature-branch + PR workflow. **GitHub repo `basilalshukaili/omani-reception` will be created public via `gh` CLI** (gh v2.92.0 confirmed installed and authenticated 2026-05-20 with `repo` + `workflow` + `gist` + `read:org` scopes). Local repo initialized at planning end.

---

## 18. Open Questions for User

Before I spawn the implementation swarm, please confirm or amend:

**Q1.** Your message ended with "After each phase, produce" (truncated). I am interpreting this as: *after each phase, produce a phase report in `docs/phase_reports/phase_<n>.md` containing what was built, decisions, risks, demo evidence, and gate verification.* **Confirm or correct.**

**Q2.** ~~Is there a **native Omani speaker** we can put in the dialect-review loop, even informally?~~ **ANSWERED 2026-05-20:** Yes — Basil (project lead) is the in-loop reviewer. Has already corrected 4 lexicon entries during planning (§6.3) and committed to a live teaching session post-implementation (§6.9). R1 risk reduced from High to Medium. Live correction loop with `/teach` command is now a first-class feature.

**Q3.** Should `generic_demo` impersonate a **specific industry** (clinic / salon / hotel / restaurant / workshop) or stay **deliberately generic** (a small services firm with appointments + info + hours + escalations)? I default to *deliberately generic* unless told otherwise.

**Q4.** **Default LLM provider for prod evaluation:** I plan to A/B Gemini Pro, Claude Sonnet 4.6, and GPT-4o in P4 and report results. Any preference on which we recommend as the default for customer-facing? (Default is "best Omani-index winner of the A/B".)

**Q5.** **Cost ceiling for the build phase:** any budget cap for LLM/embedding spend during development? (Default: I'll stay on Gemini free tier where possible and report estimated spend if I hit paid endpoints.)

**Q6.** **Where will this run in production?** Not blocking for the scaffold (Docker Compose works everywhere), but knowing the target (own VPS / Railway / Fly / AWS / Azure) lets me tune the runbook. **Default: agnostic, deployable anywhere Docker runs.**

**Q7.** Are you OK with me **proceeding autonomously through P0→P7** once you approve this plan, with phase-report check-ins at the end of each phase but no per-decision pause? Or do you want to gate every phase manually? **Default: autonomous with phase-end check-ins.**

---

## 18.5 Resolved / captured during planning (2026-05-20)

- **Telegram bot identity verified:** `@techmate_reception_bot` ("Receptionist"), token validated via `getMe`.
- **Admin chat_id captured:** Basil — `880315854`. Will be wired into `.env` as `TELEGRAM_ADMIN_CHAT_ID` for `/teach` command authorization.
- **Native-speaker reviewer secured:** Basil. R1 mitigation upgraded (§15).
- **Lexicon corrections received (5):** ويش / ايوا / كيف الحال / كيف اقدر اخدمك (initial 4) + **لو تكرم rejected** (added 2026-05-20). Captured in §6.3 and persisted to long-term memory under `C:\Users\basil\.claude\projects\C--Users-basil-Share-reception\memory\`.
- **Response-length rule received:** "do not flood the user with a huge reply for a small conversation; depend on context." Encoded in §6.8 + §10 `persona.response_style`.
- **Live teaching loop confirmed:** user will run a simulated conversation post-implementation. `/teach` command and `scripts/apply_corrections.py` are first-class deliverables (§6.9).
- **LLM scope locked:** Gemini-only live for v1 (Flash for turns, Pro for eval). $5 USD total spend cap. Embeddings switched to `text-embedding-004` (free).
- **Regional + register decision:** Muscat / Sahili Omani region, official-respectful register, plural-of-respect default. §6.2.5 / §10.
- **Demo business industry:** deliberately generic small-services firm (confirmed default).
- **Production hosting:** agnostic Docker; runbook covers any host (confirmed default).
- **Autonomy mode:** P0→P7 autonomous with phase-end check-ins (confirmed default).
- **Collaboration:** Git + GitHub, feature-branch + PR flow, two developers (Basil + friend, non-concurrent). See §20.
- **`gh` CLI confirmed installed and authenticated** (v2.92.0, account `basilalshukaili`, scopes: `repo, workflow, gist, read:org`). Binary at `C:\Program Files\GitHub CLI\gh.exe` — not yet on this shell's PATH so I'll invoke via full path until a fresh terminal is started.
- **GitHub repo decision:** **PUBLIC**, named `omani-reception`, owner `basilalshukaili`. Decided 2026-05-20.

---

## 19. What happens next

After your approval (or amendments), I will:

1. Create `STATE.md` and the `docs/phase_reports/` directory.
2. Spawn P0 with parallel sub-agents for: skeleton & pyproject, docker-compose, config loader+schema, ADR-0001/0007/0009, pytest+ruff+mypy scaffolding.
3. Verify the P0 gate myself.
4. Commit P0 deliverables (no git remote yet — local commits).
5. Produce `docs/phase_reports/phase_0.md`.
6. Proceed to P1, and so on.

---

---

## 20. Collaboration & GitHub workflow

Two developers (Basil + friend) collaborate, **non-concurrent** by agreement. Even with non-concurrent work we use a feature-branch + PR flow so history stays clean and either developer can review the other's changes before merging.

### 20.1 Local setup (now)

- `git init` in `C:\Users\basil\Share\reception` (done at end of planning).
- `.gitignore` excludes: `.env`, `__pycache__/`, `*.pyc`, `.venv/`, `node_modules/`, `*.log`, `data/`, `*.sqlite`, IDE folders.
- First commit: `PLAN.md` + `.gitignore` + skeleton README.
- Branch policy: `main` is protected; all work via `feature/*` branches.

### 20.2 Remote setup (you do this, instructions in README)

Two options:

**Done 2026-05-20 via gh CLI:** `gh repo create omani-reception --public --source=. --remote=origin --push` — repo lives at `https://github.com/basilalshukaili/omani-reception` (public). Collaborator (your friend) added by you separately via Settings → Collaborators.

### 20.3 Friend's onboarding

Add friend as a collaborator (Settings → Collaborators → Add). They:
```powershell
git clone git@github.com:<you>/omani-reception.git
cd omani-reception
copy .env.example .env       # fill in their own dev keys
docker-compose up -d         # boots Postgres + Redis
uv sync                       # installs Python deps
python -m engine.cli health  # verifies setup
```

### 20.4 Day-to-day workflow

```
git checkout main
git pull
git checkout -b feature/<short-name>
# ... edit, commit ...
git push -u origin feature/<short-name>
gh pr create  # or open in web UI
# wait for review (other dev or self-review for solo work)
# merge via squash on GitHub
git checkout main && git pull && git branch -d feature/<short-name>
```

### 20.5 Files we ship to support this

- `.gitignore`
- `.gitattributes` (LF line endings — Windows + Linux mixed team)
- `README.md` with the quickstart above
- `CONTRIBUTING.md` with: branch naming (`feature/`, `fix/`, `docs/`), commit message style (Conventional Commits — `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`), PR template requirements (description, test plan, screenshots/transcripts for bot changes)
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/ISSUE_TEMPLATE/bug.md` and `feature.md`
- `.github/workflows/ci.yml` — runs lint + mypy + tests on PRs; deferred but stubbed
- `CODEOWNERS` — both Basil and friend listed for everything (mutual review)

### 20.6 Secrets handling (critical)

- `.env` is **gitignored** — never committed.
- `.env.example` lists every env var with a placeholder value (no real keys).
- `business.yaml` files reference `${VAR}` syntax; never embed secrets.
- Telegram bot token, Gemini API key, Postgres passwords: all `.env`-only.
- Each developer holds their own `.env` locally.
- If a key ever leaks into a commit: rotate it immediately, then `git filter-repo` or BFG to scrub history, force-push (this requires explicit user authorization since force-push to main is destructive).

### 20.7 Decisions and history

Architecture decisions land in `docs/adrs/`. Phase reports land in `docs/phase_reports/`. Both are markdown, both versioned with the code — so a reviewer reading a PR sees the *why* alongside the *what*.

---

**Awaiting your sign-off.** Reply with approval (or amendments) to launch P0.

### Final blockers I need from you before P0:

**B1.** **Phase report explainer (was Q1):** After each phase (P0–P7), I'd write `docs/phase_reports/phase_<n>.md` containing: (a) what was built, (b) decisions made + ADRs landed, (c) any deviations from this PLAN, (d) demo evidence (transcripts/screenshots), (e) the gate-verification checklist, (f) running cost-to-date. You read it, give a thumbs-up or a redirect, and we move to the next phase. **OK to proceed with this format?**

**B2.** **Region confirmation:** I'm defaulting to **Muscat / coastal (Sahili) Omani** as the regional pin (rationale in §6.2.5). If you'd prefer **interior** or **Dhofari**, say so — I'll switch the seed lexicon and phrase library. **OK with Muscat default?**

**B3.** **GitHub repo name and visibility:** I suggest `omani-reception`, **private**. Override if you want a different name or visibility. (I can't create the repo myself — `gh` isn't installed. You'll create it via web UI or after `winget install GitHub.cli`; I'll give you the exact `git remote add` command after you tell me the URL.)
