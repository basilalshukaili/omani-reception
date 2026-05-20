<!--
Fill every section. Delete sections only if they truly do not apply, and say why.
-->

## What changed

<!-- 1-3 sentences. Plain English, no jargon. -->

## Why

<!-- Motivation. Link to issue / ADR / phase report if relevant.
     Examples: Closes #42 / Implements ADR-0007 / Part of phase_3.md milestone 2 -->

## Test plan

<!-- Markdown checklist. What you ran, what should still work. Attach Telegram
     transcripts or screenshots for any bot-behavior change. -->

- [ ] `uv run pytest -m "unit"` passes locally
- [ ] Manual smoke test: <describe the conversation you ran through the bot>
- [ ] Verified existing behavior unchanged: <list>
- [ ] Screenshots / transcripts attached (if user-visible change)

## Dialect impact

<!-- Did you touch engine/dialect/, businesses/<biz>/phrases/, prompts, or
     few-shot examples? Required answer below. -->

- [ ] **No** dialect-related changes — skip the rest of this section
- [ ] **Yes**, dialect-related. Native-speaker review status:
  - [ ] Reviewed and approved by: <name>
  - [ ] Pending review (PR is draft until reviewed)
  - [ ] Reviewer waived (explain why):

## Cost impact

<!-- Did you add an LLM call, retrieval pass, embedding generation, or any
     paid API call? -->

- [ ] **No** cost-relevant changes
- [ ] **Yes**, added the following calls per conversation turn:
  - Provider / model:
  - Estimated input tokens:
  - Estimated output tokens:
  - Estimated cost per turn (USD):
  - Running total against the **$5 build cap**:

## Checklist

- [ ] `ruff check` clean
- [ ] `ruff format --check` clean
- [ ] `mypy engine` clean
- [ ] `pytest -m "unit"` passing
- [ ] ADR added under `docs/adrs/` if this is an architectural change
- [ ] `CONTRIBUTING.md` updated if this changes a contributor-facing process
- [ ] No secrets in the diff (eyeballed `git diff --cached`)
- [ ] Branch name follows convention (`feature/`, `fix/`, `docs/`, `chore/`, `refactor/`, `test/`)
