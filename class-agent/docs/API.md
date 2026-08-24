# Phase 4 HTTP API

FastAPI is a transport adapter over `AuthenticationService`, `CourseAgentService`, and `ConversationStore`. It does not own identity, authorization, history, or runtime policy. The production application is created with `course_server.api:create_app`; tests inject in-memory adapters and a scripted runtime.

## Routes

Canonical routes use `/api/v1`:

```text
GET  /api/v1/health

POST /api/v1/auth/login
POST /api/v1/auth/logout
GET  /api/v1/auth/me

GET  /api/v1/conversations
POST /api/v1/conversations
GET  /api/v1/conversations/{conversation_id}

POST /api/v1/conversations/{conversation_id}/run
POST /api/v1/conversations/{conversation_id}/run/stream
POST /api/v1/agent/run
```

The final route accepts `conversation_id` and `text`. It returns JSON normally and SSE when the request sends `Accept: text/event-stream`. Unversioned aliases exist during Phase 4 development but are intentionally absent from OpenAPI.

## Sessions and authorization

The server accepts identity only from the `class_agent_auth` and `class_agent_anon` cookies. Both are `HttpOnly`, `Secure`, `SameSite=Lax`, and scoped to `/`. Access codes and session tokens are never returned in JSON.

Public requests receive isolated, expiring anonymous sessions. Authenticated user IDs and roles are reconstructed from server-side session state. Conversation ownership is checked before detail, run, and stream operations; an absent or foreign conversation returns the same `404` response.

## Streaming

Streaming responses use `text/event-stream`. Agent text is represented as:

```text
event: message
data: {"type":"agent.text.delta","text":"The "}

event: message
data: {"type":"agent.text.delta","text":"answer"}

event: message
data: {"type":"agent.text.done","text":"The answer"}
```

Zero or more `agent.text.delta` messages append provider-produced final-answer
text while the run is active. `agent.text.done` carries the canonical complete
answer so clients can reconcile their accumulated text before `event: done`.
Adapters without incremental output send one fallback delta followed by the same
completion event.

The stream begins with a transport-level status event:

```text
event: status
data: {"type":"agent.status","stage":"preparing_context","label":"Preparing conversation context"}
```

The concrete runtime may also emit brief, explicitly user-facing progress text
before a non-final tool call:

```text
event: progress
data: {"type":"agent.progress.delta","text":"I’ll read the syllabus first."}
```

These deltas update a transient activity entry. They are neither final-answer
text nor canonical conversation messages, and clients must not append them to
the answer. They contain only ordinary assistant content intended for the user;
private reasoning remains unavailable.

Tool and resource activity use `event: platform` with their canonical event type,
and stream completion uses `event: done`. The smolagents adapter reports the same
portable events placed in `AgentResult` through an optional application-owned
observer while the run is active. Its final-text observer decodes only the
arguments of the model's final-answer tool call. A separate progress observer
accepts only explicit user-facing assistant content; private reasoning and
non-final tool-call arguments are never sent to the client. Runtimes without
these optional behaviors still work. The stable `AgentRuntime` interface remains
unchanged, and provider-specific framework objects never enter the stream.

Unexpected runtime failures return a generic `503` for JSON requests or a structured `system.error` SSE event. Provider exception messages, request data, credentials, and tracebacks are not sent to clients.
