# HTTP API

FastAPI is a transport adapter over `AuthenticationService`, `CourseAgentService`, `ConversationStore`, and the public course resource catalog. It does not own identity, authorization, history, or runtime policy. The production application is created with `course_server.api:create_app`; tests inject in-memory adapters and a scripted runtime.

## Routes

Canonical routes use `/api/v1`:

```text
GET  /api/v1/health

POST /api/v1/auth/login
POST /api/v1/auth/logout
GET  /api/v1/auth/me

GET  /api/v1/notifications
POST /api/v1/notifications/{notification_id}/read
GET  /api/v1/notification-center
POST /api/v1/notification-center/{item_id}/read

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
POST /api/v1/conversations/{conversation_id}/ta-questions/{question_id}/confirmation
POST /api/v1/conversations/{conversation_id}/instructor-messages/{message_id}/confirmation
POST /api/v1/conversations/{conversation_id}/continue
POST /api/v1/conversations/{conversation_id}/greeting

POST /api/v1/conversations/{conversation_id}/run
POST /api/v1/conversations/{conversation_id}/run/stream
POST /api/v1/agent/run
```

The TA-question confirmation route accepts only `send` or `cancel`, plus a bounded
`reporter_visibility` of `named` or `anonymous`. On `send`, the browser may submit the complete
reviewed `question` shown in the confirmation; edits on `cancel` are rejected. The stored subject
and optional context remain unchanged. It requires an authenticated student who owns both the conversation and the pending
question. `send` queues work for the
separate mail worker; the HTTP request never contacts the email provider. Missing, foreign, and non-student
questions fail closed. Repeating the same decision is idempotent; trying the opposite decision
after the question has advanced returns `409`.

The instructor-message confirmation route accepts only `send` or `cancel`. On `send`, the browser
may submit the complete reviewed `subject` and `message`; a pending-question reply also submits the
separate bounded `publication_decision` of `private` or `publish`. Partial edits, a standalone
visibility value, and edits on `cancel` are rejected. It requires the active instructor who owns
both the conversation and pending message.
Recipients were already resolved
against active student accounts and snapshotted by the instructor tool; the browser cannot add or
replace them. `send` makes an ordinary message visible in only those students' logged-in
notification and agent contexts. When the draft is linked to a pending question, the editable body
is command-free, confirmation records the separately selected visibility and answer against that
question, and only the clean answer—not a moderation command or duplicate message—is projected to
the student. Content
edits for an ordinary message and its status transition are one conditional store operation; an
online answer uses its linked message ID as an idempotency key before completing that transition;
`cancel` creates no delivery. A missing, foreign, or previously resolved
message fails closed.

The continuation route accepts only a server-issued `trigger_event_id` from the owned
conversation. Platform code permits the Course Agent to continue only from explicitly allowlisted
trusted action events, currently TA-question and instructor-message Send and Cancel. It does not append a fabricated
`user.message`; the agent receives a neutral description of the completed action as its current
input. That description explicitly says the platform transition has already succeeded so the agent
does not mistake a completed Send for an unavailable future action, while the exact question remains
available in trusted event context. The continuation does
not prescribe or prewrite the agent's response. The tool that prepared the completed action is
withheld for that continuation turn to prevent it from recursively opening another confirmation,
while every other authorized capability
remains available. Repeating the same continuation returns its existing agent response instead of
running the model twice.

The greeting route accepts no prose or user identity. It requires an authenticated principal who
owns a new conversation and generates one idempotent Course Agent welcome from a platform-authored
page-load trigger. The server supplies current role-filtered attention items through ordinary agent
context. Repeating the route for that conversation returns the existing greeting; a conversation
with unrelated prior events fails closed. No fabricated `user.message` is appended. Only after a
successful result, the server acknowledges that user's current one-time Updates projection;
Communications and Upcoming are not consumed by the greeting.

The notification routes require the exact active `student` role. The list contains unread
staff-approved FAQ publications; acknowledgement is idempotent and scoped to the authenticated
user. Neither route accepts a user ID, and marking an item read does not deactivate shared FAQ
knowledge. These two routes remain as the narrow Phase 10 compatibility surface.

The notification-center routes require an active authenticated course account and derive identity
and role from the session. The response is a path-free projection with `notifications`,
`communications`, `upcoming`, and `lecture_slides` sections. The additive `lecture_slides`
section reuses `course_update` items with no read acknowledgement or unread count; it remains
in `history_items` only and is ordered by descending lecture number. The browser reveals it
when **See more** is selected. An optional `thumbnail` supplies the authorized resource URI and
registered asset ID of the first-slide preview; it contains no backing path. It is excluded from
agent greeting attention. This extends the application endpoint only; no versioned core schema
or persisted data changes or migrations are needed. Its `items` list contains the current active
projection; the page greeting uses its notification items, excluding slides. Its separate `history_items` list retains authorized read updates and
messages, resolved question threads and replies, and past deadlines in newest-first category order.
Students see their own sent question threads and
confirmed instructor messages addressed to them; an answer replaces its pending question item. TAs and instructors see queued/open student questions; other roles do
not. Course releases come from authorized resource metadata and released structured assignments;
upcoming assignment deadlines come from the same role-filtered assignment store used by the agent.
Only unread course updates, staff replies, and delivered instructor messages are dismissible.
Historical items are derived from the same durable source records and acknowledgement state; the
browser does not create a second canonical history. Mark-read first verifies that the
item exists in the caller's current authorized projection; it never accepts a user ID or arbitrary
resource path. Staff replies and instructor messages may include a `sender` object containing only
the active staff account's first name. Its opaque `course://instructors` resource URI and registered
portrait asset ID are included only when that portrait resolves. The response never exposes the
responder's email, an arbitrary image URL, or a filesystem path; `sender` is `null` only when the
staff account itself cannot be resolved and authorized.

There is intentionally no general assignment filesystem route. Assignment records are available
through the Course Agent's role-scoped `course.list_assignments` and `course.get_assignment` tools,
while the notification-center route exposes only their bounded path-free projection. There is no
assignment authoring route or tool. `course.get_assignment` emits a validated read-only workspace
panel containing the exact authorized Markdown record. Stored assignment paths and private records
remain outside the browser contract.

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
application UUID through the private applicant store. It requires an authenticated instructor
or a student with that UUID explicitly shared,
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

Application sharing update: authenticated students may use the existing application-review
tools and photo route only for accepted application UUIDs explicitly shared in the private
`student-access.json` registry. Instructor access remains unrestricted. See
[STORAGE.md](STORAGE.md) for authorization, provisioning, and revocation details.
