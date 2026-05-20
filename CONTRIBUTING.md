# Contributing to Omani Reception

Thanks for working on this. Read this once, then keep it open in a tab for the first few PRs.

## Setup

You should be running in under 10 minutes.

1. Clone:
   ```bash
   git clone https://github.com/basilalshukaili/omani-reception.git
   cd omani-reception
   ```
2. Copy env template and fill in keys:
   ```bash
   cp .env.example .env
   ```
   Mandatory keys:
   - `TELEGRAM_BOT_TOKEN` — from `@BotFather`
   - `GEMINI_API_KEY` — from Google AI Studio

   Optional (only set if you're working on the related subsystem): `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `QDRANT_URL`, `REDIS_URL`, `LANGFUSE_*`.
3. Start infra:
   ```bash
   docker-compose up -d
   ```
4. Install Python deps (uv preferred, pip works):
   ```bash
   uv sync --extra dev
   # or
   pip install -e ".[dev]"
   ```
5. Smoke test:
   ```bash
   python -m engine.cli health
   ```
   You should see green checks for Telegram, Gemini, and the local services you started.

If health fails, fix that first — do not start coding against a broken local environment.

## Branch policy

- `main` is protected. CI must pass and one review is required before merge.
- All work happens on feature branches. Pick the prefix that matches the change:
  - `feature/<topic>` — new capability
  - `fix/<topic>` — bug fix
  - `docs/<topic>` — documentation only
  - `chore/<topic>` — tooling, deps, housekeeping
  - `refactor/<topic>` — behavior-preserving structural change
  - `test/<topic>` — tests only
- **Never push directly to `main`.** Open a PR.

## Commit style

[Conventional Commits](https://www.conventionalcommits.org/). One concept per commit.

- Allowed types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `perf`, `build`, `ci`
- Scope is optional but encouraged: `feat(rag): add Qdrant hybrid search`
- Subject ≤ 72 chars, imperative mood ("add", not "added")
- Body explains **why**, not what — the diff already shows what
- Sign off co-authors when an AI assistant helped meaningfully:
  ```
  Co-Authored-By: Claude <noreply@anthropic.com>
  ```

Example:
```
feat(dialect): add fallback for unknown Omani idioms

Returns a clarifying question in dialect instead of MSA when the
classifier confidence is below 0.6. Avoids the jarring register
shift native speakers flagged in the P2 review.

Co-Authored-By: Claude <noreply@anthropic.com>
```

## PR workflow

1. Push your branch:
   ```bash
   git push -u origin feature/<topic>
   ```
2. Open a PR (`gh pr create` or the web UI). The template will appear — fill every section.
3. Request review from the other collaborator. If you're working solo on this PR (other collaborator unavailable), self-review with a note in the PR description explaining what you checked and why no second pair of eyes was practical.
4. Address review comments with new commits — do not force-push mid-review.
5. Once approved and CI is green, **squash-merge** from the GitHub UI. Edit the squash message to be a clean Conventional Commit.
6. Delete the branch after merge (the UI offers this).

## Quality bar

Before opening a PR, run locally:

```bash
uv run ruff check engine tests
uv run ruff format --check engine tests
uv run mypy engine
uv run pytest -m "unit"
```

All four must pass. CI re-runs them and will block the merge if any fail. If you need to skip a slow or flaky test temporarily, mark it with `@pytest.mark.skip(reason=...)` and open an issue — do not delete tests.

## Secrets

- **Never** commit `.env`, API keys, tokens, OAuth secrets, signed JWTs, or any file containing real customer messages.
- `.gitignore` covers the obvious cases, but **eyeball your diff** before `git add`. `git diff --cached` is your friend.
- If a secret leaks:
  1. Rotate it immediately at the provider (Telegram, Google AI, etc.)
  2. Scrub history with `git filter-repo` or BFG Repo-Cleaner
  3. Force-push the rewritten history — **coordinate explicitly** with the other collaborator first, since force-push to `main` destroys their local state
  4. Open a `chore(security): ...` PR documenting what leaked and what was rotated

## Dialect contributions

The Omani Arabic lexicon and phrase library live under:
- `engine/dialect/` — shared dialect logic, classifiers, register rules
- `businesses/<biz>/phrases/` — per-business phrase packs

Rules:
- **Native-speaker corrections supersede AI-drafted entries.** Always. If a native speaker says a phrase is off, it's off.
- When you reject a proposed phrase, document the reason in the commit message (register too formal, wrong region, sounds translated, etc.). Future contributors need to know why.
- Tag the PR with `dialect` so the native-speaker reviewer is auto-pinged via CODEOWNERS (once that mapping exists).

## ADRs (Architecture Decision Records)

Any architectural choice worth explaining gets an ADR:
- File: `docs/adrs/NNNN-title.md` (zero-padded, sequential)
- Format: MADR-lite — `Status`, `Context`, `Decision`, `Alternatives considered`, `Consequences`
- Reference the ADR number in your PR description (`Closes ADR-0007` or `Implements ADR-0012`)

If you're not sure whether something needs an ADR: if a future contributor would ask "why did they do it this way?", write the ADR.

## Phase reports

Each phase (P0 through P7, see `PLAN.md`) ends with a phase report:
- File: `docs/phase_reports/phase_<n>.md`
- Contents: what shipped, demo evidence (transcripts / screenshots), open issues, **cost-to-date against the $5 build cap**
- Subsequent work that builds on a phase appends a section to the existing report rather than creating a new file.

## Getting help

- Architecture questions → `PLAN.md`, especially §20 for this collaboration workflow
- Stuck on a phase → look at the relevant `docs/phase_reports/phase_<n>.md` for context
- Found a process gap → open a PR against this file. Process improvements are first-class work.
