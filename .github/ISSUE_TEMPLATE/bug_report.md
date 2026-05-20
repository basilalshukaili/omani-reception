---
name: Bug
about: Something is wrong with the bot or engine
title: "[bug] "
labels: ["bug"]
---

## Describe the bug

<!-- One or two sentences. What's broken? -->

## Steps to reproduce

<!-- Be specific. Paste the exact Telegram message that triggered the issue,
     and any preceding turns needed to set up the state. -->

1.
2.
3.

**Expected reply:**

<!-- What should the bot have said? -->

**Actual reply:**

<!-- What did it actually say? Paste verbatim. -->

## Environment

- Business config: <e.g. `businesses/clinic_a` or `businesses/restaurant_b`>
- LLM provider / model: <e.g. `gemini-2.0-flash`, `gpt-4o-mini`>
- Runtime: <`docker-compose` / local `python -m engine.cli` / deployed>
- Git SHA or branch:
- OS:

## Logs

<!-- Paste structlog JSON output if available. Wrap in a fenced block. Trim to
     the relevant turn(s); use a gist if it's longer than ~50 lines. -->

```json

```

## Additional context

<!-- Screenshots, related issues, suspected root cause, anything else. -->
