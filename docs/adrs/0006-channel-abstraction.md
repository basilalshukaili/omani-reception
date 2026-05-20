# ADR-0006: Channel abstraction

- **Status:** Accepted
- **Date:** 2026-05-20
- **Deciders:** Basil Al-Shukaili (project lead), Claude (engineering)
- **Phase:** P1 — LLM Adapter & Chat Loop
- **Related:** [PLAN.md](../../PLAN.md) §11 (Telegram Adapter & Future Voice), §1.2 (Architecture diagram), §1.4 (Data flow for one turn), §17 #7 (Voice deferred to v2), ADR-0001, ADR-0002

## Context

The Omani Reception engine ships with one transport in v1 — Telegram — but PLAN.md §11 and §17 #7 commit the architecture to a clean path for voice (STT/TTS) and future web/IVR channels in v2 without engine rework. The orchestrator (PLAN.md §1.4) needs a uniform message object on the way in and a uniform send call on the way out; everything below that — long-polling vs. webhook, Telegram update parsing vs. STT, audio attachment handling — is transport-specific noise that the engine must not see.

The constraints that shape this decision: (a) PLAN.md §1.1 rule 2 demands an adapter at every external seam, and the inbound network surface is the most external seam there is; (b) PLAN.md §16 #3 requires a Telegram round-trip for ten representative customer questions, so the Telegram adapter must be a complete, in-prod implementation, not a stub; (c) PLAN.md §17 #7 defers voice to v2 but is explicit that the *architecture* must already support it; (d) the dev host has no public HTTPS endpoint, so the v1 Telegram implementation must work over long-polling with zero inbound network configuration; (e) per PLAN.md §15 R10, the dev `chat_id` is discovered by an early `/start` — the channel layer needs to surface metadata cleanly so the rate limiter, security pipeline, and observability can consume it.

The orchestrator's contract with the transport is small: receive a `ChannelMessage` carrying `text`, `attachments`, and `metadata`; emit a `ChannelMessage` reply to a given `chat_id`; never know what kind of transport is on the other side.

## Decision

An abstract **`Channel` interface** lives at `engine/channels/base.py` with the contract shown in PLAN.md §11: async `start()`, async `send(chat_id, content)`, and an `on_message(handler)` registration for the orchestrator's inbound callback. `ChannelMessage` (defined in `engine/core/types.py`) is the transport-neutral shape — `text: str`, `attachments: list[Attachment]`, `metadata: dict[str, Any]` — and is what the orchestrator consumes throughout PLAN.md §1.4 steps 1–12.

The only concrete adapter in v1 is `engine/channels/telegram.py`. It uses **`python-telegram-bot` v21** in long-polling mode, configured via `config.channels.telegram` (ADR-0007). The adapter:

- Parses Telegram `Update` objects into `ChannelMessage` instances at the boundary; the engine never sees a raw `Update`.
- Surfaces `chat_id`, username, and Telegram-specific metadata via `ChannelMessage.metadata` for downstream consumers (security, observability).
- Honors `config.channels.telegram.allowed_chat_ids` if set, rejecting other chats at the channel layer before the orchestrator ever sees them.
- Reads `TELEGRAM_BOT_TOKEN` from the environment via the config loader's `${VAR}` interpolation (ADR-0007).

Future adapters — voice (STT in, TTS out), web chat, IVR, WhatsApp Business — implement the same `Channel` interface. Voice uses `attachments` to carry audio blobs and the orchestrator orchestrates STT before and TTS after; engine code does not change. Webhook mode for Telegram itself is a runtime flag on the same `TelegramChannel` class for P5+, not a new adapter.

## Alternatives considered

### Option A — Embed Telegram directly in the orchestrator (no Channel ABC)
- **Pros:** Less code today; no abstraction to maintain.
- **Cons:** Violates PLAN.md §1.1 rule 2; voice (PLAN.md §17 #7) and web/IVR adapters would require orchestrator surgery and re-testing the entire turn loop. The provider-agnosticism principle from ADR-0002 applies symmetrically here — transport-agnosticism is the same principle for the inbound side.
- **Verdict:** Rejected. The cost of the ABC is one small file; the cost of skipping it is paid in P5+ when voice lands.

### Option B — Webhook-only Telegram (no long-polling)
- **Pros:** Lower per-turn latency; canonical for production deployments.
- **Cons:** Requires a public HTTPS endpoint with a valid TLS certificate and reverse proxy on the dev host. PLAN.md §17 #2 commits to Docker Desktop on a Windows dev host, where exposing a public HTTPS endpoint is non-trivial and adds infra that v1 does not need. Long-polling needs zero inbound network and works behind any NAT.
- **Verdict:** Rejected for v1. Webhook mode is a config flag on the same `TelegramChannel` class, landing in P5+ when there is a production deployment target to webhook against.

### Option C — Generic OpenChat / Matrix bridge as the abstraction layer
- **Pros:** A universal chat protocol could in principle bridge Telegram, Discord, Slack, etc., reducing per-channel work.
- **Cons:** Adds a bridge process to operate; introduces protocol-translation lossiness for transport-specific features (typing indicators, message edits, inline buttons); none of the channels we actually care about for v1/v2 (Telegram, voice, web) are first-class in such bridges. The marginal portability gain is paid for with real operational complexity.
- **Verdict:** Rejected. Direct adapters per channel keep the system small and the failure modes legible.

### Option D — Treat Telegram's `Update` object as the canonical message type
- **Pros:** No translation layer between the SDK and the engine; zero parsing code.
- **Cons:** Locks the orchestrator, dialect pipeline, memory layer, and observability to Telegram's data model. Voice (no `Update` analog), web chat (different shape), and IVR (no text at all) would each require either a fake `Update` or a parallel code path. The transport-neutral `ChannelMessage` shape is small (text + attachments + metadata) and costs almost nothing to maintain.
- **Verdict:** Rejected. A tiny canonical shape is strictly better than coupling the engine to one SDK's update format.

## Consequences

### Positive
- Orchestrator and all downstream modules consume one shape (`ChannelMessage`) for the lifetime of the project, on any transport.
- Voice adapter in v2 is a drop-in: implement `Channel`, fill `attachments` with audio, let the orchestrator wrap STT/TTS around the existing turn loop.
- Webhook vs. long-polling is a config switch inside `TelegramChannel`, not a new class — operational mode does not leak into the engine.
- Per-channel access control (`allowed_chat_ids`) lives at the channel boundary, where it belongs, not scattered across the security pipeline.
- Test seams are clean: `tests/e2e/test_telegram_loop.py` can substitute a fake channel that emits `ChannelMessage` objects, without involving Telegram at all.

### Negative / accepted trade-offs
- One extra abstraction layer to maintain. Acceptable: the ABC is a handful of methods and the v1 adapter is bounded by `python-telegram-bot`'s surface, not ours.
- Telegram-native conveniences (inline keyboards, message edits, reply markup) must be passed through `ChannelMessage.metadata` rather than first-class fields. We accept this — those features can land per-adapter without changing the engine if we ever need them.
- Channel-layer rejection of disallowed chats means the security pipeline never sees them, which is the right answer for v1 but means audit logs of rejected chats live at the channel layer, not in the central observability stream. Mitigation: the channel logs rejections via `structlog` using the same logger config as the engine.

### Follow-ups
- Webhook mode is deferred to P5+; document the toggle in `docs/runbook.md` when it lands.
- Voice adapter (`engine/channels/voice.py`) is out of v1 scope per PLAN.md §17 #7. When v2 starts, this ADR is the contract it implements against — no amendment expected.
- If a second channel adapter lands during v1 (unlikely), it gets a follow-up ADR rather than an edit here.
- ADR-0007 already covers the `channels.telegram` config block; no schema changes needed here.
