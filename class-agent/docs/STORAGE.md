# Server storage

PostgreSQL stores durable server-side identity and canonical conversation history. Raw access codes and raw session tokens are never stored, and no smolagents objects are persisted.

## Tables

- `schema_migrations`: immutable applied version/checksum records;
- `users`: user profile, role, active state, and Argon2id access-code hash;
- `auth_sessions`: hashed authenticated tokens and revocation/expiry metadata;
- `anonymous_sessions`: hashed temporary public-session tokens and expiry metadata;
- `auth_login_failures`: hashed rate-limit keys and timestamps;
- `conversations`: one explicitly user- or anonymous-session-owned conversation;
- `events`: canonical JSON event envelopes with JSONB payload and metadata;
- `course_resources`: normalized public resource text and PostgreSQL full-text index;
- `faq_entries`: individually addressable active and inactive FAQ records;
- `ta_questions`: private student escalation, explicit confirmation, delivery, and resolution state;
- `ta_answers`: one private matched staff answer plus event and student-notification outbox state;
- `mail_inbound_receipts`: provider-message deduplication and rejected/unmatched dispositions;
- `mail_sync_state`: per-mailbox polling checkpoint with an overlap window;
- `faq_review_candidates`: durable staff decision and FAQ-publication outbox state;
- `course_notifications`: one global notification for each email-published FAQ entry;
- `course_notification_reads`: per-student acknowledgement state;
- `notification_item_reads`: per-user acknowledgement for deterministic resource releases and
  private staff replies shown by the notification center. A successful authenticated app welcome
  acknowledges its one-time Updates snapshot; Communications and Upcoming keep their independent
  active-state lifecycle. Acknowledgement hides an item from the active projection but does not
  delete its durable source record; the notification history derives read/resolved items from those
  same records.
- `instructor_messages`: instructor-owned pending, sent, or cancelled in-app message content and
  confirmation state tied to the originating conversation;
- `instructor_message_recipients`: the fixed active-student recipient snapshot for each message.

Conversation messages are represented by `user.message` and `agent.message` events. The database does not store a smolagents agent, memory object, pickle, or provider-specific conversation object.

Later-phase tables from the constitution are added only when their owning application feature is implemented.

Migration `0005_ta_email` introduces the private-email slice of Phase 10. Migration
`0006_email_faq_review` adds explicit staff email moderation, FAQ publication, login notifications,
and the student's named/anonymous presentation choice. Mail rows reference the canonical user and
conversation; they do not store access codes, provider tokens, client secrets, or a second copy of
the student's email address. `faq_entries` remains the canonical shared knowledge store, while
`course_notification_reads` records only per-account acknowledgement.
Migration `0007_single_reply_faq_decision` adds the `pending_publication` outbox state and explicit
receipt dispositions for `PUBLISH`, `PRIVATE`, and malformed replies. Historical
`pending_delivery` and `pending_review` states remain readable so an upgrade can finish work created
by the former two-reply flow.
Migration `0008_faq_archives` is retained because it was already applied during development.
Migration `0009_local_faq_knowledge` immediately removes those superseded archive-import columns;
new deployments apply both in order and end with no archive-import state.
Migration `0010_notification_center` adds generic per-user read receipts for derived center items.
It is additive: existing FAQ notification rows and `course_notification_reads` remain valid, and no
canonical event, workspace state, or course-resource content is migrated.
Migration `0011_instructor_messages` adds private instructor message records and recipient
snapshots. It does not backfill existing notifications or conversations. Delivery is a status
transition after explicit confirmation; bounded subject/body edits are persisted in that same
conditional transition while recipient rows remain fixed. The generic notification read table records each
recipient's later acknowledgement.
Migration `0012_online_question_answers` links an instructor confirmation draft to one pending
question and marks the resulting `ta_answers` row as email- or online-originated. The nullable
provider fields remain required for email answers, while online answers use the linked instructor
message for idempotency. Both origins share the existing FAQ candidate and answer notification
outboxes; question-reply message rows are excluded from direct-message projection.
Migration `0013_online_answer_retention` makes question deletion clean up its linked confirmation
draft while keeping the durable answer independent from later instructor-conversation retention.

## Course assignments

`ASSIGNMENT_DATA_PATH` defaults to `var/assignments/`. Each assignment is a separately validated
`<assignment_id>.json` file; the ID must match its filename. The store creates the directory with
mode `0700` and tool-created files with mode `0600`, rejects path indirection and unknown fields,
and refuses to overwrite an existing ID. Validated updates require the reviewed current revision,
atomically replace that one record, and preserve its original creator and creation time. Student
and TA reads expose only released published records; instructor reads may also include drafts and scheduled records. See
[ASSIGNMENTS.md](ASSIGNMENTS.md) for the complete schema and authoring workflow.

Current writes use assignment schema version 3 and store the full student-facing document as
Markdown. Platform code generates the assignment ID and derives a short notification summary. The
store accepts exact legacy version-1 and version-2 shapes only for compatibility, projects their
structured text into Markdown, and omits the former version-1 grading field. The next instructor-
approved revision migrates either legacy file to version 3; reads alone do not mutate stored files.

## Temporary chat uploads

`UPLOAD_DATA_PATH` defaults to `var/uploads/`. Uploads are stored in server-generated
UUID directories with mode `0700` and files with mode `0600`. They are scoped to the
authenticated user or anonymous session that created them, limited to 10 MB, and expire
after 24 hours. Expired directories are removed opportunistically. Temporary uploads do
not belong in backups unless an operational policy explicitly requires them. Owned
documents are exposed only through expiring `upload://` resource authorization and the
principal-scoped content endpoint.

## Course applications

Course applications are intentionally stored as private directories rather than public
resources. `APPLICANT_DATA_PATH` defaults to `var/applicants/`; directories are created
with mode `0700` and files with mode `0600`. Names contain only a server timestamp and
server-generated UUID. Each accepted application contains structured `application.json`
and a durable copy of its validated photo. Model-controlled text cannot choose a path.
The tool result stores only a receipt summary in its completion event, although the
user's original conversation messages remain part of ordinary conversation history.

New application records use `schema_version: 2`. Version 2 separates School, Department,
Research group, Degree, and Year of degree start, and separates School from Registration.
Existing version 1 files remain immutable historical records and require no database or
filesystem migration; any staff-side reader must branch on `schema_version` rather than
reinterpret the former combined fields.

Authenticated instructors receive read-only tools to list and read all applications.
Both `instructor.list_applications` and `instructor.read_application` accept an optional
boolean `accepted_only` (default false). With true, instructors use the same private UUID
allowlist as students. Accepted-only reads reject IDs outside that allowlist before reading
any record. Students remain restricted regardless of the flag. Missing or empty allowlists
produce empty accepted-only listings; malformed allowlists deny the filtered operation.
Unfiltered instructor access continues to work even if the allowlist is unavailable.
The list response remains an array; its event summary distinguishes accepted-only results.
This optional argument is additive: existing calls and persisted application schemas remain
valid, with no core contract version change or migration required.

Authenticated students receive the same three `instructor.*` tool IDs for compatibility,
but platform code restricts their access to explicitly shared accepted application UUIDs.
Anonymous, TA, and admin principals cannot use these tools. Authorization is checked before
catalog disclosure and again at execution, including every ID in an image batch before
any photo is loaded or sent to the model.

The deployment-owned `APPLICANT_DATA_PATH/student-access.json` is the sharing authority:

```json
{"schema_version": 1, "application_ids": []}
```

The server-local `APPLICANT_DATA_PATH/accepted-applicants.json` is the instructor-approved
roster used for initial server provisioning. It contains private student information: never
commit it or register it as a public course resource. The filename is ignored by Git in any
directory. Install it directly on the server with mode `0600`, separately from Git deployment.
At API or CLI startup, before accepting submissions, the server resolves that
roster against the existing applications in `APPLICANT_DATA_PATH` (default `var/applicants/`).
It writes the matching UUIDs once to `student-access.json`, plus a private
`student-access-resolution.json` report for every roster entry. Both files have mode `0600`
and are ignored by Git. The code and tests contain no real roster; tests use fictional fixtures.
If the local roster is absent, startup skips initialization and student access remains closed
unless an existing UUID allowlist already grants access. No empty snapshot is written merely
because the roster is missing, so installing it and restarting can initialize access later.

Matching normalizes Unicode, case, whitespace, parentheses, and name order. A roster entry can
explicitly provide alternative names in its `aliases` list. Each person must match exactly one existing
application; duplicates are blocked rather than choosing the latest submission. When the record
has a School field, it must agree with the roster institution (MIT Media Lab counts as MIT).
Historical records without School can match by name. Department labels are retained as roster
context, not fuzzy authorization criteria. Missing, ambiguous, or conflicting entries stay
blocked and appear in the resolution report; uniquely matched people remain available.

This bootstrap deliberately trusts the instructor's assertion that the existing server corpus
contains the accepted people. Submitted names alone cannot establish identity. Inspect the
private report after deployment; uncertain matches require instructor verification. Once an
access file exists, startup **never replaces or expands it**, including an empty or malformed
file. Subsequent submissions with an accepted name cannot grant access, and explicit revocations
survive restarts. The initial resolution report is a snapshot, not a live view of later edits.

Deployment: pull the code on the real server, verify `APPLICANT_DATA_PATH` points to its
existing application directory, install the private roster there, and restart the API.
Git pulls cannot supply the roster. Its format is shown below with fictional data:

```json
{
  "schema_version": 1,
  "applicants": [
    {"name": "Ada Example", "institution": "MIT", "department": "Example", "aliases": []}
  ]
}
```

Review the startup matched/unresolved counts
and the private resolution report. No UUID transcription is needed for unambiguous matches.
A development server with only test applications generates an empty local snapshot; do not copy
that ignored file to production. If a prior `student-access.json` already exists, it remains the
authority. To resolve an unresolved entry, verify its application UUID and explicitly add it to
that file. Do not delete the snapshot to rerun name matching against later unreviewed submissions.

At tool/photo execution, authorization uses only the UUID snapshot, never name matching.
Changes are read on each request, so removing an ID revokes future tool reads and photo requests
without restarting. Previously returned content in conversation history is not erased by
revocation. Back up the private roster, UUID allowlist, and resolution report with applicant records. Malformed access files deny
student access; missing files outside the startup flow share nothing.

Student record reads return submitted application fields and photo metadata, but omit internal
principal, upload-ID, and storage metadata. Instructors retain their existing complete-record
view. Tool events store only summaries; user-visible answers remain ordinary conversation history.
Photos require an explicit visual-inspection request and keep the existing provider-side
no-storage and image-analysis restrictions. Only tool-issued `applicant://{application_id}/photo`
references may be displayed in that turn. The existing `/instructor/applications/{id}/photo`
route now checks the same sharing policy for students; denied requests return `404` and successful
responses use `Cache-Control: private, no-store`.

This is an explicitly requested extension of application visibility to students. No persisted
application schema, core interface, tool argument schema, or URI version changes, and no
application/database migration is needed. The authorized startup bootstrap creates a new private
sharing snapshot without modifying existing applications. An empty snapshot intentionally exposes no applications.

## Migrations

Apply migrations with:

```bash
uv run python -m course_server.migrations apply
uv run python -m course_server.index_resources
```

Migration filenames are ordered and checksummed. Never edit an applied migration; add a new migration instead. The runner refuses to continue if a committed migration differs from the checksum recorded by a database.

## Backups

Example backup and restore commands:

```bash
pg_dump --format=custom --file=class-agent.dump "$DATABASE_URL"
createdb class_agent_restored
pg_restore --dbname=class_agent_restored class-agent.dump
```

Production backups must cover PostgreSQL, shared course storage, the assignment directory, and the
private applicant directory. Temporary uploads normally remain outside backups. Periodically
test restoration rather than assuming a backup file is usable.

## Local published FAQ knowledge

The agent-facing staff-approved FAQ is one versioned JSON document. Its default location is:

```text
var/course-knowledge/published-faq.json
```

Set `PUBLISHED_FAQ_PATH` to use another local path. The dedicated mail worker creates and atomically
replaces the file after an authorized `PUBLISH` reply; the API and Course Agent CLI read the same
path through `course://faq`. The file is ignored by Git and contains only FAQ ID, question, answer,
timestamps, and active state. Student identity, private context, responder identity, mailbox data,
and notification-read state remain outside it.

The file is intentionally local runtime state. It survives ordinary process restarts as long as
the local file remains, but this repository does not require a second export, remote mount, or
automatic backup. Deleting it removes the agent's learned FAQ overlay; maintained static FAQ
content under `shared/course/faq/` is unaffected.

## Student self-exclusion

Peer selection uses the existing account email and accepted application records, with no extra
identity file. All student application listings exclude records with that email; own-profile
reads resolve the email to a unique accepted application. Website candidate lists apply the
course's first-name repository naming convention after resolving the same account email.
The existing accepted UUID allowlist remains the access authority. See
[STUDENT_PROJECTS.md](STUDENT_PROJECTS.md#peer-recommendations-and-self-exclusion) for ambiguity
handling, direct own-record reads, deployment, and compatibility.

## PostgreSQL integration tests

Set `TEST_DATABASE_URL` to a disposable development PostgreSQL database and run `uv run pytest -m postgres`. Tests create a random isolated schema and drop that schema afterward. They do not modify the database's public schema.
