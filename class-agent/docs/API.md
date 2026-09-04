# HTTP API

FastAPI is a transport adapter over `AuthenticationService`, `CourseAgentService`, `ConversationStore`, and the public course resource catalog. It does not own identity, authorization, history, or runtime policy. The production application is created with `course_server.api:create_app`; tests inject in-memory adapters and a scripted runtime.

## Routes

Canonical routes use `/api/v1`:

```text
GET  /api/v1/health

POST /api/v1/auth/login
POST /api/v1/auth/logout
GET  /api/v1/auth/me

GET  /api/v1/course/resources
GET  /api/v1/course/resources/content?uri={resource_uri}
GET  /api/v1/course/resources/asset?uri={resource_uri}&asset_id={asset_id}
GET  /api/v1/instructor/applications/{application_id}/photo
POST /api/v1/uploads?filename={filename}

GET  /api/v1/conversations
POST /api/v1/conversations
GET  /api/v1/conversations/{conversation_id}
POST /api/v1/conversations/{conversation_id}/workspace/actions
POST /api/v1/conversations/{conversation_id}/workspace/interactions

POST /api/v1/conversations/{conversation_id}/run
POST /api/v1/conversations/{conversation_id}/run/stream
POST /api/v1/agent/run
```

`GET /api/v1/course/resources` returns path-free metadata for resources authorized to the
current principal. Anonymous visitors receive the six public resources. Students also
receive resources registered under the student audience, and instructors receive both
student and instructor resources. It never returns private applicant files, temporary
uploads, or server filesystem paths.

`GET /api/v1/course/resources/content` resolves one authorized registered URI to its
original bytes and media type for a trusted native viewer. The URI is checked against
the principal's resource catalog before reading; model- or browser-provided filesystem
paths are never accepted.

Role-scoped resource content and assets use `Cache-Control: private, no-store`. An unknown
or unauthorized URI returns the same `404` response so the route does not disclose private
resource existence.

`GET /api/v1/instructor/applications/{application_id}/photo` resolves only a server-issued
application UUID through the private applicant store. It requires an authenticated instructor,
returns `404` to every other role, and serves validated image bytes with private no-store caching.
It never accepts or exposes a filesystem path. The browser reaches this route only after resolving
an `applicant://{application_id}/photo` URI issued by the instructor image-inspection tool.

`POST /api/v1/conversations/{conversation_id}/workspace/actions` accepts only `focus`
and `close` for an existing panel UUID. It checks conversation ownership, reconstructs
workspace state, validates the operation against the registered component, and appends
the resulting canonical event. It cannot introduce an arbitrary component or props.

`POST /api/v1/conversations/{conversation_id}/workspace/interactions` records a
schema-limited calendar selection/view change or document page/find action as
`workspace.interaction`. The server verifies that the panel exists and that the action
matches its registered component before appending the event. Bounded application-draft
edits are saved even when they do not yet satisfy the final submission rules; the
resulting panel update marks the field as a candidate and carries a field-specific
`validation_error`. Structurally invalid or oversized draft edits return `422` with a
structured `code`, optional `field_id`, and user-safe `message`.

`POST /api/v1/uploads` accepts the file as the raw request body, its original name in
the required `filename` query parameter, and its media type in `Content-Type`. It
returns a principal-scoped upload UUID, metadata, and expiry time. Uploads are limited
to 10 MB and expire after 24 hours. Supported types are JPEG, PNG, WebP, GIF, PDF,
JSON, CSV, Markdown, and plain text; course applications accept only JPG/JPEG, PNG, or WebP
for the required photo. The same session cookie must own both upload and tool call.
`GET /api/v1/uploads/{upload_id}/content` serves that same owned, unexpired artifact to
DocumentViewer with private no-store caching; foreign and expired receipts return `404`.

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

Non-final model content is discarded. It is not transported as an SSE event or
projected into chat. Clients receive verified platform activity and decoded
final-answer text only.

Tool and resource activity use `event: platform` with their canonical event type,
and stream completion uses `event: done`. The smolagents adapter reports the same
portable events placed in `AgentResult` through an optional application-owned
observer while the run is active. Its final-text observer decodes only the
arguments of the model's final-answer tool call. Private reasoning and
non-final tool-call arguments are never sent to the client. Runtimes without
these optional behaviors still work. The stable `AgentRuntime` interface remains
unchanged, and provider-specific framework objects never enter the stream.

Validated `workspace.panel.opened`, `workspace.panel.updated`, and
`workspace.panel.closed` events use the same `event: platform` channel. Clients must
validate and reduce the enclosed command; they must not interpret it as arbitrary UI
code.

Unexpected runtime failures return a generic `503` for JSON requests or a structured `system.error` SSE event. Provider exception messages, request data, credentials, and tracebacks are not sent to clients.
