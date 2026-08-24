# Architecture invariants

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
