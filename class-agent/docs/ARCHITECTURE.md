# Architecture decisions through Phase 5

The platform has one logical production agent, `course-agent`. A request combines that shared agent policy with a trusted principal, conversation context, authorized tools and resources, and available device capabilities. Phase 1 defines the portable contracts needed to express that boundary; Phase 2 resolves trusted principals from access-code and anonymous sessions; Phase 3 persists canonical conversation events and runs the first CLI-accessible adapter; Phase 4 exposes those services through FastAPI without moving transport concerns into the core; Phase 5 adds a static React client over those HTTP contracts.

## Decisions

### Supported toolchains

The minimum versions are Python 3.11 and Node.js 20. Python uses Pydantic 2 for domain contracts and a `Protocol` for the runtime boundary. TypeScript uses ordinary exported types. These are language bindings for the same JSON wire representation.

### Contract authority

Versioned JSON Schema under `shared/schemas/` is the language-neutral authority for serialized contracts. Python and TypeScript definitions remain intentionally explicit rather than being generated so students can read them directly. Shared fixtures and tests detect drift among the schema, Python models, and TypeScript types.

All protocol payloads are JSON values. This is a deliberate narrowing of Python's general `Any` type so durable state cannot accidentally depend on Python objects.

### Schema versions

The current contract version is `1`. Every `Event` carries `schema_version`; the schema directory version governs the other serialized models. See [SCHEMA_VERSIONING.md](SCHEMA_VERSIONING.md).

### Core boundary

`agent_core` owns domain models plus the asynchronous `AgentRuntime` and generic `ModelProvider` interfaces. It has no knowledge of FastAPI, databases, MCP SDK implementations, smolagents, React, or provider APIs. Adapters may depend inward on the core; the core must never depend outward on them.

`AgentContext` explicitly contains the principal and the already-filtered tool and resource identifiers supplied to a runtime. Authorization policy is not implemented in Phase 1, but this shape makes the authorization result inspectable and prevents a runtime adapter from needing model-controlled identity arguments.

### Validation choices

- Unknown fields are rejected to surface protocol drift.
- Authenticated principals require a user identity and cannot also carry an anonymous identity.
- Anonymous principals require an anonymous session, have only the `public` role, and cannot carry user profile fields.
- Identifiers, names, capability IDs, and user text that must be meaningful reject blank strings.
- Timestamps must be timezone-aware.
- Lists that represent sets reject duplicates.
- An obtainable capability must explain its acquisition mechanism.
- Permission ownership is explicit: exactly one user or anonymous session owns a permission.

## Stable interfaces

The stable platform interfaces through Phase 5 are:

- `PrincipalContext`
- `Event`
- `Conversation`
- `Memory`
- `Capability`
- `Permission`
- `Node`
- `AgentContext`
- `AgentInput`
- `AgentResult`
- `AgentRuntime`
- `ModelProvider`
- `shared/schemas/v1/agent-core.schema.json`

Changing one requires contract tests, documentation, and a schema-version review. Persistence migrations will also be required once later phases store these contracts.

## Deliberately deferred

MCP servers, workspace commands and dynamic components, the Agent Bridge, and a browser extension remain deferred to their constitution phases. The authentication service continues to return an opaque credential without depending on HTTP; the FastAPI adapter alone translates credentials into cookies.

## Deviations and clarifications

There are no architectural deviations from the constitution. The following underspecified choices were resolved for Phase 1:

- The project directory is named `class-agent` as requested.
- The minimum runtime versions are Python 3.11 and Node.js 20.
- JSON Schema is canonical for wire data.
- JSON-only payloads replace unconstrained in-memory `Any` values at serialization boundaries.
- Fields not defined by the constitution for `Capability`, `Permission`, `AgentContext`, `AgentInput`, and `AgentResult` are kept to the minimum needed to express the documented boundary and examples.
- Docker Compose begins in Phase 2 with the reference PostgreSQL service only.

## Phase 2 additions

`course_server.auth` owns authentication behavior and depends on its `AuthStore` protocol. `PostgresAuthStore` and `InMemoryAuthStore` are replaceable adapters. Neither PostgreSQL records nor Argon2 implementation objects cross into `agent_core`.

Authentication and anonymous session tokens are random opaque bearer credentials. Only domain-separated hashes are persisted. User access codes contain 160 random bits and only Argon2id hashes are persisted. User administration, code resets, deactivation, role changes, principal reconstruction, login throttling, and session revocation happen in application code outside prompts.

Phase 2 adds two constitution-compatible support tables not listed in the minimum schema summary: `anonymous_sessions` implements temporary public identity and `auth_login_failures` implements failed-login rate limiting. Tables belonging to later product features are intentionally deferred to later migrations.

Optional credential email delivery is deferred to the `MailAdapter` phase. The Phase 4 FastAPI transport enforces and tests the required `HttpOnly`, `Secure`, and `SameSite=Lax` cookie flags.

## Phase 3 additions

`Conversation` is now a portable core contract with exactly one authenticated-user or anonymous-session owner. PostgreSQL persists conversations and canonical `Event` envelopes through an application-owned `ConversationStore`; raw framework memory is never stored.

`runtime_smolagents` implements `AgentRuntime` with `ToolCallingAgent`, not `CodeAgent`. It reconstructs prior user/agent text from events, receives only pre-authorized tools, emits portable run/tool/resource/message events, and discards all smolagents objects after the run. `OpenAIModelProvider` is the first `ModelProvider` adapter and obtains its key from server-side configuration.

The initial internal tool and resource conveniences use canonical dotted tool IDs, resource URIs, and JSON input schemas so they translate directly to MCP. No MCP server or proprietary external tool protocol is introduced in Phase 3. The only initial capability is public `course.read_syllabus` over `course://syllabus`.

The default automated runtime test uses a scripted smolagents model and never invokes an external API. The PostgreSQL integration test validates both authentication and conversation/event round trips in an isolated schema.

Adding `Conversation` to schema v1 is backward compatible: it adds a new definition and does not change the representation or validation of an existing contract. No schema-version increment is required.

## Phase 4 additions

`course_server.api` is an application factory with injected-service and production modes. Production startup opens one PostgreSQL connection pool and constructs the existing authentication, conversation, runtime, and Course Agent adapters. FastAPI depends inward on these boundaries; no core contract imports FastAPI.

Opaque authenticated and anonymous credentials are accepted only from `HttpOnly`, `Secure`, `SameSite=Lax` cookies. Each request reconstructs its principal through `AuthenticationService`. An invalid, expired, or revoked authenticated cookie falls back to an isolated anonymous session rather than becoming an authorization bypass. Conversation list, detail, run, and stream routes check ownership in application code before reading history or invoking the runtime.

Canonical HTTP routes are versioned under `/api/v1`. Unversioned aliases are temporarily available for the Phase 4 development clients but omitted from OpenAPI. Ordinary runs return a compact portable result; streaming runs use Server-Sent Events. The runtime still returns one `AgentResult`, so Phase 4 streams the typed events available after a run without modifying the stable `AgentRuntime` interface.

Phase 4 adds no durable schema and changes no stable core representation, so schema version 1 and the existing PostgreSQL migrations remain unchanged.

## Phase 5 additions

`apps/web` is a Vite application that depends only on the public protocol types,
the first-party UI package, and the Phase 4 HTTP API. It builds to ordinary
static assets and assumes same-origin `/api/v1` in production. The development
server proxies that path to FastAPI.

The default workspace deliberately presents a single current projection of the
conversation: submitting a prompt immediately clears the prior Course Agent
response, and the reset process trace is the only run content shown until the
new response begins. An expandable process trace reports stream/tool activity. An empty
conversation presents the Course Agent as the class website and invites course
questions or application inquiries. User composition is a borderless textarea
at the bottom, with Enter to submit and Shift+Enter for a newline. Durable
history remains on the server; it is not discarded merely because the primary
view is minimal.

The fixed header contains only the MIT and MIT Media Lab marks plus an About
control. The white `Course Agent` identity and muted expandable process trace sit
in the response stage immediately above the answer; the trace retains its exact
last action when a turn completes. About, login, and conversation navigation
live in an intentionally secondary drawer opened from the About control. Public
use remains unblocked. Conversation
ownership and role resolution continue to happen on the server; the client sends
cookies and never accepts or constructs a user ID for privileged operations.

`packages/ui` now contains the small reusable control set and CSS-variable token
foundation needed by Phase 5. Component registries, typed workspace state,
document/calendar views, and MCP workspace tools remain Phase 7 work. Phase 5
adds no durable schema and changes no stable interface.

The concrete smolagents adapter also offers an optional `run_observed` method to
the application layer. It reports the same portable events eventually returned
in `AgentResult` as they occur. `CourseAgentService` falls back to ordinary
`AgentRuntime.run` for every other runtime, so the stable runtime protocol is not
expanded and runtime replacement remains possible. FastAPI uses this observer to
stream verified run, tool, and resource activity; it does not expose private
model reasoning.

The adapter has a second transient channel for concise assistant progress
messages such as an announced next tool action. It accepts only ordinary
assistant content deliberately addressed to the user, never reasoning or tool
arguments. FastAPI transports it as `agent.progress.delta`, and the browser
temporarily projects it in the main response area while a neutral activity state
marks the update in the trace. The next public progress or final response
replaces that projection. Progress text is not persisted as an `agent.message`
and never joins the final response.

When the application supplies a text observer, that concrete adapter enables
smolagents' native provider stream and incrementally decodes only the
`final_answer` tool-call argument. FastAPI emits those fragments as
`agent.text.delta`, then emits the canonical complete result as
`agent.text.done`. The browser ingests these events immediately and independently
paces their visible projection at about 50 Unicode characters per second, without
backpressuring agent execution. This adds readable live final-output movement
without persisting partial messages, exposing intermediate reasoning, or
changing the stable `AgentRuntime` contract. Runtimes that only implement `run`
keep the non-streaming fallback.

The expandable browser trace projects only portable activity already authorized
for the principal: statuses, runtime/model identifiers, exact tools and
arguments, resources, tool results, and completion. Iconography and monospace
styling distinguish this operational evidence from the Course Agent's final
message. Explicit public progress may temporarily occupy the main response area,
while private reasoning remains outside the transport and UI.
