# Class Agent implementation instructions

This file applies throughout `class-agent/`. Read the repository-root `AGENTS.md` first.
`CONSTITUTION.md` remains the architectural source of truth; this file translates it into
day-to-day implementation constraints.

## Required preflight

Before changing code:

1. Read `README.md` for current implementation status and phase.
2. Read the constitution sections governing the feature and the relevant file in `docs/`.
3. Inspect adjacent code, tests, schemas, and registries to find the established extension
   point.
4. Decide explicitly whether each new choice belongs to the Course Agent, deterministic
   platform code, configuration, a registry, a resource, or a design token.
5. Check for a nearer `AGENTS.md` before editing a subdirectory.

Do not begin from a generated implementation and retrofit the architecture afterward.

## Architecture invariants

1. There is one logical Course Agent.
2. Authentication/authorization is enforced in application code, never only through prompts.
3. MCP is the canonical executable tool/resource boundary.
4. Agent Skills use standard `SKILL.md` directories.
5. Interactive third-party agent UIs use MCP Apps.
6. First-party workspace components use the registered component protocol.
7. `agent_core` must not import FastAPI, React, or PostgreSQL.
8. smolagents must remain behind `AgentRuntime`.
9. Never persist smolagents internal objects as canonical history.
10. Local file contents must not be uploaded automatically.
11. Privileged tools must derive identity from `PrincipalContext` rather than model-controlled user IDs.
12. Run all contract tests before modifying stable interfaces.

`CONSTITUTION.md` is the architectural source of truth. Implement its phases in order. Do not add work from a later phase without an explicit request.

Additional non-negotiable invariants:

13. Treat model output as untrusted input at tool, resource, persistence, and UI boundaries.
14. The model receives only tools and resources already authorized for its trusted
    `PrincipalContext`.
15. Course data lives in registered resources; components display data; tools control
    actions. Do not permanently embed maintained course content in component code.
16. Workspace state is a projection of portable events and validated commands, never a
    serialized React tree or model-generated implementation.
17. Native renderers are an explicit trusted map. External or student interactive UI
    belongs in a sandboxed MCP App, not arbitrary React mounted into the host.
18. Configuration and provider-specific behavior stay outside portable contracts and
    canonical history.
19. A capability or internal failure must never be faked. Return a safe structured
    limitation or error and let the agent explain it accurately.

## Where choices belong

Use this decision table before hardcoding behavior:

| Kind of decision | Correct owner | Examples |
| --- | --- | --- |
| User-intent-dependent presentation or tool use | Course Agent | Calendar versus DocumentViewer; which authorized resource to read |
| Trust, access, or external effects | Platform code | identity, tool filtering, path scope, confirmation, redaction |
| Changeable runtime/deployment value | Typed configuration | model ID, step limit, API base, quotas, feature flag |
| Discoverable capability or renderer metadata | Registry/schema | component props, supported operations, resource metadata |
| Maintained course information or workflow knowledge | Resource or standard Skill | schedule, syllabus, application instructions |
| Reusable visual value | UI token or semantic variant | color, spacing, radius, image presentation |
| Durable cross-language representation | Versioned schema plus bindings | events, workspace commands, stable domain contracts |

The Course Agent should choose semantically from authorized capabilities. Never implement
ordinary chat intent recognition as a list of words or phrases in React, FastAPI, or route
handlers. Product shortcuts may invoke an explicit canonical action, but free-form user
language remains agent-owned.

Platform code must hardcode and test trusted allowlists, validators, ownership checks,
security bounds, renderer maps, protocol constants, and safe fallbacks. Do not make these
model-configurable merely to avoid a constant.

Values expected to vary between deployments or over the life of the course must not be
copied into multiple call sites. Put them in typed settings, resource manifests, generated
registries, canonical course files, or UI tokens as appropriate.

## Stable interfaces

Treat these contracts as stable: `PrincipalContext`, `Event`, `Conversation`, `Memory`, `Capability`, `Permission`, `Node`, `AgentContext`, `AgentInput`, `AgentResult`, `AgentRuntime`, `ModelProvider`, `WorkspaceState`, `WorkspaceCommand`, `ComponentManifest`, and the versioned JSON Schemas under `shared/schemas/`.

Changes to a stable interface require:

- a schema-version decision;
- updated Python and TypeScript contract definitions;
- migration notes when persisted data is affected;
- updated contract fixtures and tests;
- relevant documentation updates.

## Repository boundaries

- `python/agent_core` contains domain models and abstract interfaces only.
- `packages/protocol` contains the TypeScript representation of wire contracts.
- `shared/schemas` is the language-neutral wire-contract authority.
- Keep framework, database, transport, and model-provider details outside the core packages.
- Persist only portable data. Do not use pickle or framework-owned serialized state.
- Treat model output as untrusted input at every capability and UI boundary.
- `python/course_server` owns application orchestration and adapters; keep route functions
  thin enough to expose rather than contain domain behavior.
- `python/runtime_smolagents` is the only production package that may construct smolagents
  runtime objects. Translate at its boundary and discard transient framework state.
- `packages/workspace` owns framework-independent workspace parsing, validation, and
  reduction. It must not depend on React renderers.
- `packages/ui` owns reusable first-party rendering primitives and design tokens.
- `apps/web` composes the product and HTTP/event flows; it must not become a second source
  of protocol, authorization, resource, or component truth.
- `shared/course` is the maintained course-content authority. Edit source manifests/files,
  not generated aggregate registries.
- `database/migrations` is append-only permanent history. Never rewrite an applied
  migration to change current behavior.

## Implementation discipline

- Search for the nearest existing pattern before creating a new file or abstraction.
- Prefer adding a focused domain module over enlarging `api.py`, `App.tsx`, runtime prompt
  construction, or capability catalogs with unrelated feature logic.
- Do not duplicate Python/TypeScript contract knowledge in ad hoc dictionaries or types.
- Keep pure parsing, validation, projection, and policy logic separate from I/O so it can
  be tested without a server, browser, database, or model call.
- Do not add prompt instructions as the only implementation of deterministic behavior.
  Put enforceable policy in code and keep procedural knowledge in the appropriate resource
  or standard Skill.
- Avoid speculative compatibility layers. Preserve compatibility deliberately when real
  persisted data, public contracts, or documented clients require it.
- Do not introduce a new framework, hosted design system, storage format, wire protocol,
  or provider coupling without documenting the strong technical reason.
- A refactor must preserve behavior with tests; do not mix broad refactors into a focused
  feature or fix unless the extraction is required to implement it safely.

## Change requirements by area

### Stable contracts

Update the canonical schema, Python binding, TypeScript binding, shared fixtures, tests,
schema-version decision, migration notes, and relevant docs together. If the change can be
additive without changing the stable contract, prefer that narrower path and document why.

### Course resources

Keep human-readable and machine-readable representations aligned where both exist. Use
opaque registered URIs and asset IDs at runtime; never expose backing filesystem paths.
Regenerate derived resource catalogs with the documented indexing command rather than
editing them as independent sources.

### Runtime and tools

Tools must use trusted execution context for identity, validate model-controlled arguments,
return portable JSON-compatible results, sanitize durable events, and fail closed when
authorization or registration is missing. Provider quirks remain inside provider/runtime
adapters and must not leak into core types or history.

### Workspace and UI

The agent selects a registered semantic component; the platform validates props and maps
the manifest to a trusted renderer. Never accept arbitrary HTML, CSS, JavaScript, Tailwind
classes, React source, event handlers, or style objects from the model. Keep one current
workspace surface unless the constitution explicitly changes that product model.

### Persistence and migrations

Persist portable application-owned data, not framework objects. Analyze compatibility,
backfill, rollback, privacy, retention, and backup consequences before changing durable
state. Tests must use isolated schemas/stores and may not truncate shared databases.

## Testing expectations

- Every behavior change needs a focused regression test at the lowest useful layer.
- Authorization changes require positive and negative role/ownership cases.
- Model/tool behavior tests use scripted or mocked providers by default; normal test runs
  must not spend API credits or depend on the public network.
- UI changes require interaction/accessibility assertions when behavior changes, not only
  snapshots or text presence.
- Contract changes require the complete contract suite, not only a local unit test.
- If a check cannot run, state the exact command and reason in the handoff and PR.

## Development commands

From this directory:

```bash
uv sync
pnpm install
docker-compose up -d postgres
uv run python -m course_server.migrations apply

uv run pytest
uv run ruff check python
uv run ruff format --check python
uv run mypy python/agent_core python/course_server python/runtime_smolagents python/tests

pnpm test
pnpm typecheck

make check
```

Run `make check` before changing or submitting stable interfaces.

PostgreSQL integration tests run only when `TEST_DATABASE_URL` is set. They create and destroy a uniquely named schema; they never truncate the configured database's public schema. External model calls are mocked in the default test suite.

## Completion checklist

Before handing off a change, confirm:

- the diff contains only requested work and intentional supporting changes;
- agent/platform/config/registry/resource/token ownership is correct;
- no maintained data, deployment value, styling system, or user-intent heuristic was
  hardcoded in the wrong layer;
- existing extension points were reused or a new boundary is justified;
- relevant tests and documentation changed with the behavior;
- the final diff and `git diff --check` were reviewed;
- stable-interface, migration, privacy, security, and phase impacts are reported.
