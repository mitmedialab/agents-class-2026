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
