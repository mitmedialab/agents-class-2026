# Canonical events

`Event` is the durable history envelope. A raw chat-message array is not the canonical system history.

The envelope records a stable ID, schema version, timezone-aware timestamp, extensible event type and actor strings, optional principal/conversation/node associations, and JSON-only payload and metadata objects. At most one of `principal_user_id` and `anonymous_session_id` may be set.

Initial event names are defined by the constitution, including `user.message`, `agent.message`, agent-run and tool lifecycle events, resource reads, capability and permission changes, node connection changes, workspace panel changes, memory changes, TA email events, and `system.error`.

Event names remain strings so later phases can add names without changing the event envelope. New names should use a namespaced dotted form and must document their payload before production use.

Application logs and canonical events are separate. Ordinary logs must not become an accidental copy of prompts, private files, grades, or sensitive tool results.

## Phase 3 event payloads

- `user.message`: `text` and portable `input_id`;
- `agent.run.started` / `agent.run.completed`: portable `input_id`, with runtime metadata;
- `agent.tool.requested`: canonical `tool_id` and validated JSON arguments;
- `resource.read`: resource `uri`, never an arbitrary local path;
- `agent.tool.completed`: canonical `tool_id`, `storage_policy`, referenced resources, and only the result permitted by that storage policy;
- `agent.tool.failed`: canonical `tool_id` and a structured error category;
- `agent.message`: response `text` and portable `input_id`.

Phase 3's sample syllabus uses `server_full`. The tool adapter already honors `server_summary`, `local_only`, and `ephemeral` by omitting disallowed full results from durable event payloads.

## Phase 7 workspace payloads

- `workspace.panel.opened`: an `open` command containing the complete validated panel;
- `workspace.panel.updated`: a validated `update` or `focus` command;
- `workspace.panel.closed`: a validated `close` command.
- `workspace.interaction`: the existing panel ID/component ID, a permitted semantic
  interaction name, and its validated JSON value.

Each payload has exactly one `command` object conforming to
`shared/schemas/v1/workspace.schema.json`. Panel state is reconstructed by reducing
these events in order. The durable representation contains component IDs, resource
URIs, validated JSON props/state, and layout hints—never React elements, JavaScript,
or PDF.js objects.

## Private email payloads

- `email.ta_question.confirmation_requested`: private question ID/code, subject, exact question,
  optional explicitly selected context, and `pending_confirmation` status;
- `email.ta_question.queued` / `email.ta_question.cancelled`: question ID/code, exact question,
  optional context, and new status from the student's explicit UI action;
- `email.ta_question.created`: question ID/code, subject, and `open` status after the provider accepts
  the staff message;
- `email.ta_answer.received`: question ID/code, subject, sanitized answer, and
  `visibility: private`.

These events belong to the student's owned conversation and user principal. They never contain
mailbox credentials, the student's address, Graph payloads, or arbitrary quoted email history.
An agent continuation produced from one of these trusted actions marks its run lifecycle and
`agent.message` metadata with `trigger_event_id`; this makes retries idempotent without inventing a
user-authored chat message.
Staff email decisions and pending FAQ publications are durable workflow rows rather than private
conversation events. Publication creates a global `faq_entries` record and a
`course_notifications` record; it does not copy the originating student's identity into the public
FAQ.
