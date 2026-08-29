# Python implementation instructions

These rules apply to `python/` in addition to the repository-root and `class-agent`
instructions. Read the relevant runtime, API, auth, storage, browser, workspace, and event
documentation before changing those boundaries.

## Layer boundaries

- `agent_core` contains portable domain models and abstract interfaces. It must not import
  FastAPI, PostgreSQL adapters, smolagents, provider SDKs, browser implementations, or UI
  code.
- `course_server` owns application services, authorization policies, persistence adapters,
  transport adapters, and trusted capability execution. Route/CLI entry points should
  delegate coherent behavior to focused services or domain modules.
- `runtime_smolagents` is a replaceable adapter behind `AgentRuntime` and `ModelProvider`.
  It may construct transient smolagents objects but must return portable platform results
  and discard framework state after each run.
- Database, web search, browser, upload, and provider implementations remain replaceable
  adapters behind application-owned boundaries where reasonable.

Dependencies point inward toward portable contracts. Do not import FastAPI request types,
database connections, provider models, or renderer details into core policy and models.

## Agent choice versus enforced policy

The Course Agent may request an authorized tool/resource/component and choose among its
validated semantic options. Python platform code must enforce:

- principal identity and ownership from trusted execution context;
- capability filtering before the model sees a catalog;
- argument schemas, path/network confinement, rate and size bounds, and resource scope;
- external-effect confirmations and safe failure categories;
- event redaction, retention policy, and portable persistence.

Never expose a privileged generic operation and rely on a prompt to restrict it. Never
accept a model-controlled user ID, role, backing path, credential, installer URL, or
ownership assertion as authoritative.

Do not implement natural-language intent with keyword matching in API or service code.
Do not accumulate product workflow prose in the global runtime prompt when the behavior
belongs in deterministic policy, a maintained resource guide, or a standard Agent Skill.
Prompts may guide choices, but code must enforce every invariant that affects security,
privacy, durable state, money, or external side effects.

## Configuration, data, and persistence

- Runtime/deployment values come from validated `AgentSettings` or an equivalent typed
  configuration boundary. Do not scatter environment lookups or provider/model IDs.
- Secrets remain server-side and must never enter logs, events, exception text returned to
  clients, fixtures, prompts beyond the provider boundary, or committed files.
- Store JSON-compatible application-owned contracts. Never persist pickles, smolagents
  objects, provider messages as canonical history, or arbitrary Python state.
- Migrations are append-only and checksummed. Add a migration for durable schema changes;
  never edit an applied migration.
- Resource arguments are opaque authorized identifiers, not filesystem paths.

## Structure and tests

- Extract coherent parsing, validation, state transition, or policy logic from large API,
  runtime, and capability modules into focused testable modules.
- Avoid catch-all helpers and one-use abstraction layers. Keep I/O edges narrow and pure
  logic directly testable.
- Use typed models and explicit result/error categories. Avoid broad `Any`, unstructured
  dictionaries, and catch-all exceptions at stable boundaries.
- Add positive, negative, and isolation tests for authorization and ownership behavior.
- Mock external model/search/browser services in default tests; normal test runs must not
  require public network access or spend provider credits.
- Run the focused pytest module, Ruff, and mypy for touched packages; use `make check` for
  stable-interface changes and before submission when feasible.
