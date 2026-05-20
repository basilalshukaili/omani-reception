# ADR-0009: Methodology and phase gates

- **Status:** Accepted
- **Date:** 2026-05-20
- **Deciders:** Basil Al-Shukaili (project lead), Claude (engineering)
- **Phase:** P0 — Foundation & Conventions
- **Related:** [PLAN.md](../../PLAN.md) §13 (Methodology & Phase Gates), §14 (Testing Strategy), §16 (Acceptance Criteria)

## Context

The Omani Reception engine is a non-trivial scaffold: provider-agnostic LLM layer, Arabic-aware RAG, multi-layer dialect enforcement, function calling, memory, security, observability, channel abstraction, and a demo business — all built by a single lead agent operating largely autonomously with end-of-phase check-ins from the project lead. PLAN.md §16 lists 14 acceptance criteria that together define "done." The work must be sequenced so that each step produces a demo-able artefact, the lead can course-correct cheaply, and the running cost stays inside the $5 USD hard cap (PLAN.md §16 criterion 9).

The team has two developers (Basil + friend, non-concurrent) and one lead agent (Claude). There is no separate QA, ops, or release engineering function. Whatever methodology we adopt has to (a) produce verifiable progress at every checkpoint, (b) make it easy for either developer to drop in or out without losing context, (c) keep the surface area small enough that the lead agent can hold the whole system in head, and (d) match the project's strongest constraint — dialect quality — which cannot be tested only at the end because regressions are silent and expensive.

The natural shape of the work is incremental: foundation → LLM glue → memory & RAG → tools → dialect → security → observability → demo business. Each layer depends on the ones below it, and each layer can be demonstrated end-to-end via Telegram once the chat loop exists from P1 onward.

## Decision

We adopt an **8-phase, SPARC-flavored, demo-gated** methodology.

Concrete specifics:

- **Eight phases (P0 through P7),** as enumerated in PLAN.md §13. Each phase has a single named focus and a small set of deliverables.
- **Each phase ends with a `docs/phase_reports/phase_<n>.md` report** containing exactly: (a) what was built, (b) decisions made and ADRs that landed in this phase, (c) any deviations from PLAN.md (with rationale), (d) demo evidence (Telegram transcripts, screenshots, or scorecard CSVs depending on the phase), (e) the gate-verification checklist with every item ticked or explicitly waived, (f) running cost-to-date in USD.
- **No phase advances until its gate is green.** The gate criteria are the bulleted "Gate:" lines in PLAN.md §13 for each phase. The lead agent verifies the gate itself before producing the report.
- **Autonomous operation with phase-end check-ins.** The lead agent proceeds through P0 → P7 without per-decision pauses. The project lead reads the phase report at each handover and either approves continuation or redirects.
- **Per-decision artefacts are ADRs.** Every architectural decision lands in `docs/adrs/NNNN-*.md` in the phase where the decision is taken. The phase report cross-references the ADRs it spawned. Total ADR count is fixed at nine for v1 (PLAN.md §1.3): 0001 language/framework, 0002 LLM abstraction, 0003 pgvector, 0004 Arabic retrieval, 0005 dialect strategy, 0006 channel abstraction, 0007 config schema, 0008 security model, 0009 this one.
- **Parallel sub-agent execution within a phase.** When phase deliverables are independent (e.g., in P0: pyproject + docker-compose + config loader + ADRs + pytest scaffolding), the lead launches them as parallel sub-agents and integrates results. Sequential dependencies are honored. PLAN.md §12 documents the logical roster.
- **Native-reviewer gate is separate from the code "done" gate.** PLAN.md §16 criterion 14: the dialect quality of the live system is gated on Basil's teaching session (§6.9) before any real-customer rollout. The 8 phases produce a working scaffold; the teaching loop is a continuing, post-phase mechanism that this methodology explicitly preserves room for.

## Alternatives considered

### Option A — Single big-bang implementation
- **Pros:** No phase ceremony; one push at the end.
- **Cons:** No demo-able milestones along the way; impossible to course-correct without throwing away large amounts of work; cost runaway risk because we cannot observe per-phase spend; the project lead cannot meaningfully review progress until it is too late to redirect.
- **Verdict:** Rejected because course-correction is the single most important property for a project where dialect quality is the headline risk.

### Option B — True SPARC (Specification → Pseudocode → Architecture → Refinement → Completion) per module
- **Pros:** Formally rigorous; canonical for safety-critical work; produces excellent traceability.
- **Cons:** Heavy for a v1 scaffold. The specification step is already done — PLAN.md is the spec. The architecture step is also already done — PLAN.md §1 is the architecture. Running the full SPARC ritual per module would multiply paperwork without changing the artefacts.
- **Verdict:** Rejected as overkill. We collapse SPARC to demo-gated phases: each phase implicitly does specification (in PLAN.md), refinement (during the phase), and completion (the gate). ADRs absorb the architecture and decision-record outputs.

### Option C — Strict test-driven (write all tests first, then implement)
- **Pros:** Forces interface clarity; produces high coverage; catches regressions early.
- **Cons:** For skeleton + glue code (CLI scaffold, docker-compose, config loader entry points, structlog setup), code-first is faster and tests follow naturally. For boundary contracts (config validator, LLM adapter contracts, Arabic normalizer, dialect validator), we *do* write tests first because those interfaces must hold across providers and across regression cycles.
- **Verdict:** Partially adopted. We adopt TDD for the validator, adapter contracts, normalizer, and golden dialect set. We do not adopt it religiously for orchestration and glue.

### Option D — Continuous deployment / trunk-based per commit
- **Pros:** Tight feedback loop; canonical for mature teams with strong test pyramids.
- **Cons:** The project is too young for the discipline this requires; the team is two devs and an agent, working non-concurrently; we have no deployment target yet; the cost cap means we cannot afford to deploy speculative changes. Feature-branch + phase-end merges (PLAN.md §20) give the right cadence for this scale.
- **Verdict:** Rejected for v1. Trunk-based may be reconsidered post-v1 when there is a stable production environment and a real test pyramid.

## Consequences

### Positive
- Every phase produces a demo-able artefact and a written record. The project lead can audit progress without reading code.
- Cost-to-date is tracked at every phase boundary, keeping the $5 USD cap visible and enforceable.
- Course-correction is cheap: if dialect quality regresses in P4, we redirect there without unwinding P5/P6/P7.
- Decisions are documented in-flight via ADRs, not reconstructed at the end.
- Sub-agent parallelization keeps wall-clock time reasonable for the lead agent within a phase, without blurring the phase-end gate.

### Negative / accepted trade-offs
- Phase reports take real time to write. We accept this because their existence is the artefact that makes the autonomous-with-check-ins mode work.
- A phase that turns out to be larger than estimated (P4 dialect is the obvious candidate) blocks downstream phases until its gate is green. We accept this — the alternative is shipping a bot that sounds wrong, which is worse than slipping a phase.
- The 8 ADRs other than this one are also gating items; missing one blocks the phase report. This is intentional: decisions without records cannot be reviewed later.

### Follow-ups
- Create `docs/phase_reports/` (done in P0) and write `phase_0.md` at the close of P0 with the gate-verification checklist.
- After P4, revisit this ADR if the dialect phase shape requires sub-phases (P4a lexicon, P4b validator, P4c teaching loop). Update in place if so.
- After P7, write a meta-retrospective in `docs/phase_reports/phase_7.md` that audits whether the methodology held up — and capture any lessons in a follow-up ADR if a v2 of this document is warranted.
