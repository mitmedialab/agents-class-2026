# Repository instructions for coding agents

These instructions apply to the entire Git repository. They are a required operating
contract for AI-assisted changes, not optional background reading.

## Before editing

1. Run `git status --short` and preserve every pre-existing change.
2. For any change under `class-agent/`, read `class-agent/AGENTS.md` and every nearer
   `AGENTS.md` that applies to the files you will touch.
3. Read the relevant sections of `class-agent/CONSTITUTION.md`. It is the architectural
   source of truth. At minimum, understand its status/principles, current development
   phase, explicit boundaries, and final instruction to coding agents.
4. Inspect the nearest implementation, tests, registries, schemas, and documentation
   before proposing a new pattern. Search first; do not assume a facility is absent.
5. Keep the task within the requested scope. Do not combine it with speculative features,
   broad cleanup, dependency replacement, or work from a later phase.

If a request appears to conflict with the constitution, a stable contract, privacy, or a
trust boundary, identify the conflict before implementing it. A direct request may
authorize a new phase or deliberate architecture change, but it does not silently waive
security, migration, or documentation requirements.

## The project's design test

Optimize for composability, explicit state, portability, inspectability, and easy student
modification. Prefer the smallest clear solution over a clever framework or abstraction.
The system should make it possible to answer, from code and inspectable state:

- what the Course Agent knows and which source supplied it;
- which tools and resources it can use and why they are authorized;
- where an action executes and which permission allows it;
- which UI it can display and how that UI is validated;
- where durable history is stored.

If a change makes those questions harder to answer, revise the design.

## Decision ownership: agent, platform, or data

Place each decision in the correct layer.

### The Course Agent may choose

- among tools and resources already filtered and authorized by platform code;
- among registered workspace components and their bounded semantic variants;
- a presentation or workflow based on user intent and current conversation context;
- content and layout inside schemas that application code validates.

Do not replace these semantic choices with browser/API keyword matching, fixed prompt
phrases, or a growing tree of feature-specific conditionals. Do not invent tools,
components, permissions, resources, CSS, HTML, or executable UI at runtime.

### Platform code must decide

- authentication, authorization, identity, ownership, permission scope, and redaction;
- which tools/resources/components exist and are exposed;
- schema validation, trusted renderer dispatch, sandboxing, confirmations, and safe
  failure behavior;
- canonical persistence and external-effect boundaries.

These trust decisions must be deterministic application code and tests, never prompt-only
policy or model judgment.

### Configurations, registries, resources, and tokens should decide

- model/provider IDs, limits, endpoints, feature flags, and deployment-specific values;
- component/tool/resource metadata and bounded variants;
- course content and other maintained source data;
- colors, spacing, radii, typography roles, and reusable visual values.

Do not scatter such values through feature code. A hardcoded value is appropriate only
when it represents an intentional invariant, protocol constant, validation bound, safe
default, or explicit trusted allowlist. When adding one, make that reason evident in the
name, type, comment, test, or PR description.

## Modularity and reuse

- Reuse or extend existing components, adapters, schemas, registries, helpers, and tests
  before creating a parallel abstraction.
- Keep domain logic out of transport, framework, rendering, and entry-point modules.
- Do not solve a feature by appending special cases to a large orchestrator when the logic
  has a coherent module, policy, adapter, resource, or registry boundary.
- Extract by responsibility, not merely to reduce line count. Avoid one-off wrappers and
  speculative generic frameworks.
- Keep patches focused. Preserve behavior outside the request and avoid unrelated
  reformatting or renaming.
- New dependencies require a concrete need and must fit the constitution's portability,
  longevity, ownership, and vendor-lock-in constraints.

## Product and visual coherence

The established interface is sparse, editorial, restrained, and predominantly
monochrome. It uses a black/near-black ground, ivory primary text, muted secondary text,
fine rules, strong typographic hierarchy, generous negative space, and minimal chrome.

- Use the repository's first-party UI components and CSS variables.
- Do not introduce a competing visual language, generic dashboard/card-grid aesthetic,
  decorative gradients, arbitrary palette, font system, radius system, or scattered
  literal styling unless the task explicitly calls for a deliberate design change.
- Use semantic variants and existing tokens before adding a token. Add a token only when
  it expresses a genuinely reusable design decision.
- Preserve accessibility, keyboard behavior, responsive layouts, reduced-motion behavior,
  and safe rendering of model-controlled content.
- A visible UI change requires review at relevant desktop and narrow layouts plus targeted
  tests. Include before/after evidence in the PR when practical.

More specific frontend rules live below `class-agent/apps/web/` and
`class-agent/packages/ui/`.

## Contracts, data, and phases

- Treat versioned schemas and the named stable interfaces in `class-agent/AGENTS.md` as
  compatibility boundaries.
- A stable-interface change requires an explicit schema-version decision, synchronized
  language bindings, fixtures/tests, migration analysis, and documentation.
- Keep maintained data in resources or registries rather than embedding it in components,
  prompts, or route handlers.
- Read `class-agent/README.md` for current implementation status. Existing code from a
  later idea is not blanket permission to expand that phase.

## Verification and handoff

Before claiming completion:

1. Review `git diff --check`, `git diff --stat`, and the full relevant diff.
2. Run the smallest targeted tests while iterating, then the broadest relevant checks the
   environment permits. Use `make check` for stable interfaces and before submission when
   feasible.
3. Add or update tests for behavior changes, including failure and authorization cases.
4. Update architecture, runtime, UI, resource, or operational documentation when behavior
   or a maintained contract changes.
5. Report what changed, what was verified, any check not run and why, any migration or
   compatibility impact, and any deliberate deviation from the constitution.

Never conceal failing checks, unreviewed generated code, unresolved placeholders, or
known architectural deviations.
