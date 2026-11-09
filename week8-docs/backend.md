# Backend changes

All paths are under `class-agent/`. Base: `student/week-8-personalization-starter`.

## New files

| File | What it adds |
|---|---|
| `database/migrations/0019_peer_memories.sql` | Tables `memories` and `peer_introductions` (details below). The migration only appends; no existing table changes. |
| `python/course_server/peer_memory.py` | The store protocol, an in-memory store and a PostgreSQL store; `PeerMemoryService`, which holds every authorization and state rule; the five agent tools; and the People panel workspace command. |
| `python/course_server/peer_memory_routes.py` | Owner-scoped HTTP routes for the People panel. |
| `python/tests/test_peer_memory.py` | 9 tests (list below). |

## Database (`0019_peer_memories.sql`)

**`memories`**: one row per remembered fact. The columns follow the constitution's `Memory`
contract.

- `user_id` (owner, cascades on user delete), `kind`, `content` (500 characters at most),
  `source_event_ids` (uuid[]), `privacy`, `metadata` (jsonb), `created_at`, `updated_at`.
- `kind` is one of `background`, `goal`, `preference`, `project`, `can_help`, `needs_help`.
- `privacy` is `personal` (only the owner) or `course_private` (may be shown to classmates).
- `metadata` holds `source_excerpt`, `saved_by`, and `edited_by_student`.
- Index on `(user_id, updated_at)`, and a partial index on shared rows for matching.

**`peer_introductions`**: one row per introduction.

- `requester_user_id`, `helper_user_id` (always different people), `topic` (200 characters at
  most), `message` (2000 at most), `status`, `created_at`, `updated_at`, `sent_at`,
  `responded_at`.
- `status`: `draft` → `sent` → `accepted` / `declined`. `cancelled` is reachable from `draft`
  or `sent`.

## Service rules (`PeerMemoryService`)

- **Access.** Only an authenticated, active student. Inactive roster members, staff and
  anonymous visitors are refused, and identity always comes from `PrincipalContext`.
- **Saving.**
  - Whitespace is normalized. An identical memory of the same kind is not duplicated.
  - A student can hold at most 100 memories.
  - The source is the latest `user.message` event in the trusted conversation, plus a
    280-character excerpt.
- **Updating and deleting.** Only the owner's rows can be changed. Any edit marks the memory
  `edited_by_student`. Unknown and foreign ids get the same "not found".
- **Agent context.** `selected_memories(principal)` returns the owner's 30 newest memories.
  Other students' memories never enter another student's context.
- **Matching.** `classmate_offers(principal)` groups other active students' `course_private`
  rows per person. It returns only people with at least one `can_help` item and marks whether
  each is accepting requests.
- **Helper limits.** Each helper has at most 2 open requests and at most 3 sent in the last 7
  days. Drafting and sending both check these limits.
- **Transitions.**
  - Only the requester may `send` or `cancel`; only the helper may `accept` or `decline`.
  - Each action is allowed only from the listed states.
  - A wrong actor gets "not found"; a wrong state gets a conflict.
- **Views.** Drafts and cancelled requests are hidden from the helper. A declined request
  appears to the requester as `unavailable`.

## Agent tools

Tool ids are registered in `agent/capabilities.py` (`PEER_MEMORY_TOOL_IDS`) and built in
`agent_cli.build_runtime`. `CourseCapabilityPolicy(peer_memory_access=...)` exposes them only
to active students.

| Tool | Arguments | Effect |
|---|---|---|
| `memory.get_mine` | none | Lists the owner's memories with ids. |
| `memory.save_mine` | `kind`, `content`, `share_with_classmates` (default false) | Saves one memory with its source message and emits a `memory.created` event. The description asks for the student's name instead of pronouns, and for no guesses, grades or third parties. |
| `memory.forget_mine` | `memory_id` | Deletes one of the owner's memories. |
| `peers.find_helpers` | none | Returns classmates' shared offers and whether each is accepting requests. |
| `peers.request_introduction` | `helper_username`, `topic`, `message` | Creates a draft, which is **not sent**, and opens the People panel. |

## Wiring into the existing agent

- `agent/service.py`: new `AgentMemoryProvider` protocol. `CourseAgentService(memories=...)`
  fills the existing `AgentContext.selected_memories` field, which was previously unused.
- `runtime_smolagents/runtime.py`: when the memory tools are authorized, the prompt gains a
  section with the student's memories, marked as student-owned data, not instructions. It
  tells the agent:
  - to adapt explanations to the memories, preferring the student's own edits;
  - to save durable facts and say what it saved;
  - to keep memories private unless the student agrees to share them;
  - to call `peers.find_helpers` once when a student is stuck and offer a fitting classmate;
  - to draft an introduction only after the student agrees, and never to claim it was sent.
- `api.py`:
  - builds `PeerMemoryService(PostgresPeerMemoryStore(pool))` with the roster's
    active-student check;
  - passes it to the runtime, the capability policy and the agent service;
  - adds `AppServices.peer_memory`;
  - mounts the People routes;
  - lets `POST /conversations/{id}/workspace/open-static` accept `target: "people"`.
- `workspace/static_open.py`: adds `"people"` to `StaticOpenTarget`.

## HTTP routes (`peer_memory_routes.py`, under `/api/v1`)

All routes require a logged-in active student. A missing, foreign or forbidden item returns
`404`, and responses are `private, no-store`.

| Method and path | Body | Result |
|---|---|---|
| `GET /people/mine` | none | `{memories, introductions}` for the owner |
| `PATCH /people/mine/memories/{id}` | `content`, `privacy` and/or `kind` (other fields rejected) | the updated memory |
| `DELETE /people/mine/memories/{id}` | none | `204` |
| `POST /people/mine/introductions/{id}` | `{"action": "send" \| "cancel" \| "accept" \| "decline"}` | the owner's introductions; `409` for a disallowed state |

## Tests

`python/tests/test_peer_memory.py`:

1. Memories are owned; only shared items reach classmates; inactive students and staff are
   refused.
2. A student's edit changes visibility and marks the memory; forgetting removes it from
   matching.
3. An introduction needs the requester's Send and the helper's answer; wrong actors are
   refused; a decline shows as `unavailable`.
4. The helper request cap blocks further drafts.
5. The tools are offered to active students only.
6. Saving records the source message; extra arguments such as `user_id` are rejected; drafting
   opens the People panel.
7. The agent context carries only the owner's memories, and the prompt includes them.
8. The People routes are owner-scoped; foreign ids return `404`; unknown body fields return
   `422`.
9. The PostgreSQL store, against a real database in an isolated schema, follows the same
   rules. It runs only when `TEST_DATABASE_URL` is set.

Existing tests updated: the migration list in `test_migrations.py` and `test_postgres_auth.py`,
and the latest migration in `test_course_direct_messages.py`.

Results on this branch:

- `uv run pytest`: 443 passed, 3 failed. The same 3 fail on the unmodified starter (schedule
  resource ordering, and a Postgres auth roundtrip).
- `ruff check` and `mypy` are clean.
