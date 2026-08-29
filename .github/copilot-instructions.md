# GitHub Copilot repository instructions

`AGENTS.md` at the repository root is the canonical AI coding contract. Read and follow it
before analyzing, generating, editing, or reviewing code. For work under `class-agent/`,
also read `class-agent/AGENTS.md` and every nearer `AGENTS.md` governing the files in scope.
Read the relevant sections of `class-agent/CONSTITUTION.md`; it is the architectural source
of truth.

Do not generate an implementation until you have inspected existing code, tests, schemas,
registries, resources, design tokens, and documentation for the nearest established
pattern. Preserve pre-existing changes and keep the patch limited to the requested work.

Apply these rules in every suggestion and review:

- The Course Agent chooses semantically among already-authorized tools, resources,
  registered components, and bounded variants. Do not hardcode free-form user intent with
  prompt keyword matching in React, FastAPI, or route handlers.
- Deterministic platform code owns identity, authorization, ownership, validation,
  allowlists, redaction, sandboxing, confirmations, persistence, and external effects.
  Never rely on model judgment for a trust boundary.
- Changeable values belong in typed configuration, registries, maintained resources, or
  design tokens. Hardcode only deliberate invariants, protocol constants, validation
  bounds, safe defaults, and trusted allowlists, with an evident justification.
- Reuse existing components and extension points. Do not grow large orchestrators with
  unrelated special cases when logic has a coherent module, policy, adapter, registry, or
  resource boundary.
- Preserve the sparse monochrome editorial visual system and first-party semantic UI.
  Reject generic dashboard styling, scattered literal CSS, arbitrary model-generated UI,
  and a competing component or design system unless explicitly requested.
- Do not change stable contracts without synchronized schemas, Python/TypeScript bindings,
  fixtures, tests, migration/version analysis, and documentation.
- Do not propose speculative abstractions, dependencies, broad cleanup, or later-phase
  features as part of a focused PR.

Before stating that work is complete, review the full diff, run relevant tests and static
checks, disclose anything not run, and verify every AI-generated line integrates with the
repository rather than merely compiling in isolation.
