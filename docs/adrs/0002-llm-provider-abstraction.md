# ADR-0002: LLM provider abstraction

- **Status:** Accepted
- **Date:** 2026-05-20
- **Deciders:** Basil Al-Shukaili (project lead), Claude (engineering)
- **Phase:** P1 — LLM Adapter & Chat Loop
- **Related:** [PLAN.md](../../PLAN.md) §3 (Provider-Agnostic LLM Layer), §2 (Tech Stack & Rationale), §13 (Methodology & Phase Gates), §15 R2/R4 (cost and tool-schema risks), §17 #11 (Gemini-only assumption), ADR-0001

## Context

The Omani Reception engine must be able to drive multiple LLM providers behind a single interface. PLAN.md §3 names three: Gemini (live for v1), Claude, and OpenAI. The acceptance criterion in PLAN.md §16 #2 is that switching providers is a one-line `config.yaml` change with zero engine code edits, verified by adapter contract tests. PLAN.md §17 #11 ratifies Gemini as the only live provider during the build, with Claude and OpenAI exercised only through mocked HTTP under a $5 USD hard cost cap (§15 R2).

The provider surface area that the orchestrator actually depends on is small: an async `chat()` call that accepts messages, optional tool schemas, model, temperature, max tokens, and a response format flag; an async `stream()` variant; a `pricing` descriptor for the cost tracker (§9). The orchestrator must remain provider-blind — it consumes a normalized `LLMResponse` with text, tool calls, usage counts, finish reason, and a raw-response debug field, regardless of who served the call.

The constraints that shape this decision: (a) tool-calling schemas differ meaningfully across Gemini, Claude, and OpenAI (PLAN.md §15 R4), and the orchestrator cannot care about those differences; (b) provider-native features we want — Gemini `system_instruction`, Anthropic message/tool-result structure, OpenAI/Anthropic prompt caching, streaming — must remain accessible without leaking through the abstraction; (c) the abstraction must not become a bottleneck for new provider features as SDKs evolve; (d) per PLAN.md §13 P4, A/B testing across providers (or within the Gemini family) requires that the orchestrator never have to be changed to swap a model.

## Decision

A custom **`LLMProvider` ABC** lives at `engine/llm/base.py` with the contract shown in PLAN.md §3. Concrete adapters live as siblings:

- `engine/llm/gemini.py` — live adapter, uses `google-genai` SDK.
- `engine/llm/claude.py` — mocked-tested only, uses `anthropic` SDK.
- `engine/llm/openai.py` — mocked-tested only, uses `openai` SDK.

A factory at `engine/llm/factory.py` reads `config.llm.provider` (and an optional `--llm-provider` CLI override) and returns the configured concrete instance. Each adapter validates its own credentials at construction time and raises a clear "no API key for provider X" error when the corresponding env var is missing — never a silent default to another provider.

Tool-call schemas are unified through `engine/llm/normalize.py`. A canonical `ToolSchema` (Pydantic model) is the input the orchestrator hands the provider; the adapter translates it to the provider's native format on the way in, and translates tool-call responses back into a canonical `ToolCall` on the way out. The orchestrator sees one shape, always.

**Live exercising:** Gemini is the only provider exercised against the real API during the build, with `gemini-2.5-flash` for normal turns and `gemini-2.5-pro` for evaluation/judge calls (PLAN.md §3, §6.7). Claude and OpenAI adapters are covered by adapter contract tests using `pytest-httpx` to mock HTTP. They fail gracefully with a typed error if no live key is present — they never silently fall back.

## Alternatives considered

### Option A — LiteLLM or LangChain as the provider layer
- **Pros:** Off-the-shelf multi-provider support; one dependency instead of three SDKs; community-maintained schema translation.
- **Cons:** Wrappers add a layer of indirection and lag behind native SDKs on new features (tool use shapes, structured outputs, prompt caching, streaming nuances). Debugging a tool-call schema mismatch through two adapter layers is meaningfully harder. PLAN.md §2 estimates ~150 LoC per adapter for our needs — a wrapper saves no real work and costs us feature-velocity.
- **Verdict:** Rejected. The cost of the wrapper is paid every time a provider releases a feature we want; the saving it offers is small at our adapter size.

### Option B — Direct SDK use in the orchestrator (no abstraction at all)
- **Pros:** Minimum code; no translation layer to maintain.
- **Cons:** Bakes provider lock-in into the orchestrator; violates PLAN.md §1.1 rule 2 (adapter pattern at every external seam); makes the §16 #2 acceptance criterion (one-line provider swap) impossible without an unwind; makes the P4 A/B evaluation harness (Flash vs Pro now, cross-provider later) require code changes per run.
- **Verdict:** Rejected on principle and on phase-gate consequences.

### Option C — OpenAI-API-compatible only (treat Gemini/Claude as OpenAI-shaped via proxies)
- **Pros:** A single canonical request/response shape; many proxies exist.
- **Cons:** Translation is lossy. Gemini's `system_instruction` is structurally distinct from a `messages[0].role="system"` entry; Anthropic's tool-result message structure does not round-trip cleanly through the OpenAI tool/function calling shape. Streaming events diverge. We lose visibility into provider-native pricing fields the cost tracker (§9) needs.
- **Verdict:** Rejected. The lossiness hits exactly the surfaces (system prompt, tool calls, usage) the engine depends on most.

### Option D — OpenRouter or similar provider-router service
- **Pros:** One credential, many providers; centralized billing.
- **Cons:** Adds an external dependency and another point of failure; the cost layer is opaque, so the §16 #9 acceptance criterion (per-conversation cost computable within 5% of provider-reported usage) becomes hard to verify; prompt-cache pricing visibility per provider is lost; an extra network hop is added to every turn (§16 #10 latency budget).
- **Verdict:** Rejected for v1. May be reconsidered later if cross-provider routing becomes a real need at scale.

## Consequences

### Positive
- Orchestrator code is provider-blind. The only place a provider name appears is the factory.
- The §16 #2 acceptance criterion is mechanically demonstrable: flip `llm.provider` in `config.yaml` (with the appropriate key in `.env`), the bot routes to a different SDK with zero engine edits.
- Cost tracker (§9) consumes a normalized `usage` field with per-provider pricing pulled from each adapter's `pricing` property — straightforward to keep within the $5 USD cap (§15 R2).
- Tool calling works the same way to the orchestrator on all three providers, mitigating PLAN.md §15 R4 by construction.
- Future providers (e.g., a local Llama server) drop in by adding one file.

### Negative / accepted trade-offs
- Three adapters to maintain. Each provider's SDK upgrades may require an adapter touch-up. Acceptable: the adapters are ~150 LoC each and bounded by the ABC.
- Provider-native bleeding-edge features that don't fit the ABC must be exposed via an adapter-specific extension hook or wait for the ABC to evolve. We accept the latency this introduces in exchange for a stable orchestrator surface.
- `normalize.py` becomes a critical-path module — bugs there are silent and provider-spanning. Mitigation: contract tests exercise the round-trip (canonical → provider-native → canonical) for every supported tool-call shape on every provider.

### Follow-ups
- ADR-0007 already pins the `llm` block of `BusinessConfig`; no schema changes needed here.
- When P4 ratifies the dialect A/B harness, the same factory feeds the eval runner — no new abstraction layer is introduced.
- If a fourth provider lands post-v1 (e.g., self-hosted Llama via vLLM), add an adapter and document in a follow-up ADR rather than amending this one.
- Cross-provider live A/B is deferred until budget or keys allow (PLAN.md §3); the abstraction is ready when they do.
