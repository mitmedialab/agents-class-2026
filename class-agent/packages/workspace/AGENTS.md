# Workspace protocol instructions

These rules apply to `packages/workspace/` in addition to the repository-root and
`class-agent` instructions. Read `docs/WORKSPACE.md`, `docs/EVENTS.md`, and the workspace
schema/versioning guidance before changing commands, panels, manifests, or reduction.

## Boundary and behavior

- Keep this package framework-independent. It parses and validates portable commands,
  manifests, and state transitions; it must not import React renderers, browser APIs,
  FastAPI behavior, model SDKs, or server persistence adapters.
- Workspace state is derived deterministically from canonical events and validated
  commands. Do not introduce hidden mutable state or serialize implementation objects.
- The Course Agent may select a registered component and bounded semantic props. The
  registry/validator decides whether that request is valid, and the host maps it to an
  explicit trusted renderer.
- Reject unknown components, operations, props, variants, malformed graphs, duplicate or
  missing panels, and unauthorized resource relationships. Never silently accept a
  generated payload by weakening validation.
- Keep one current surface semantics and deterministic open/update/focus/close behavior
  unless the product contract is deliberately revised with schema, tests, and docs.
- User interactions returned to the agent must be bounded semantic actions, not DOM,
  callback, component-instance, or arbitrary JSON implementation state.

## Cross-language synchronization

The canonical workspace schema, trusted component registry, TypeScript implementation,
Python workspace binding/validator, fixtures, browser reducer, runtime tools, and docs form
one contract. Update every affected representation together and make an explicit version
decision for breaking changes.

Add fixture-driven tests for accepted and rejected commands plus reducer transitions. Run
the workspace tests, matching Python workspace tests, schema tests, and `pnpm typecheck`
for contract changes.
