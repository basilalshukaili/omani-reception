# Omani Arabic AI Receptionist

A production-quality, chat-only AI receptionist that converses in authentic **Omani Khaleeji Arabic** (Muscat / Sahili variety, official-respectful register) over Telegram. Designed as a **general scaffold**: a new business is onboarded by editing config + dropping a folder of knowledge, with **zero engine code changes**.

> **Status:** In planning. See [PLAN.md](PLAN.md) for the full architecture, methodology, and acceptance criteria. Implementation begins after sign-off.

## High-level

- **Provider-agnostic LLM** behind one interface — default Gemini, with Claude/OpenAI adapters ready.
- **Hybrid Arabic RAG** — BM25 (Postgres tsvector) + dense (pgvector) + RRF, with a dedicated Arabic normalizer.
- **Seven-layer Omani dialect defense** — prompt lexicon, few-shot phrase library, style retrieval, rules validator, optional LLM judge, correction loop, golden CI + human teaching loop.
- **Function calling, memory, security, observability, cost tracking** — all implemented.
- **One-command boot:** `docker-compose up`.

## Quickstart (after implementation)

```powershell
git clone <repo-url>
cd reception
copy .env.example .env       # fill in TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, DB creds
docker-compose up -d         # Postgres + Redis + app
uv sync                       # install Python deps
python scripts/ingest.py --business generic_demo
python -m engine.cli health
# Then talk to the bot on Telegram
```

## Documentation

- [PLAN.md](PLAN.md) — full architecture & methodology
- `docs/architecture.md` — module reference (post-P0)
- `docs/onboarding_a_business.md` — how to add a new business
- `docs/dialect_strategy.md` — deep-dive on Omani enforcement
- `docs/runbook.md` — ops, secrets, deploy
- `docs/adrs/` — every significant decision
- `docs/phase_reports/` — per-phase build evidence

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) (post-P0). TL;DR: feature branches off `main`, Conventional-Commits style, PR with a test plan, squash-merge.

## License

TBD by repo owner.
