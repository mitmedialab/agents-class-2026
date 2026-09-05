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
- `course_notification_reads`: per-student acknowledgement state.

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

Authenticated instructors receive dedicated read-only tools to list applications and read
one structured `application.json` by its server-issued application UUID. Students, TAs,
admins, and anonymous visitors never receive those tools, and the tools also recheck the
trusted principal at execution. Full records are available transiently to the instructor's
agent run but only a summary is stored in canonical tool events. Representative photos are
reported as protected metadata during ordinary record reads. If an instructor explicitly
requests visual inspection, a separate instructor-only tool may send one to four selected
photos to the configured multimodal model as in-memory data URLs with provider-side storage
disabled. Photo bytes and raw inspection output are not copied into canonical tool events;
the instructor-visible final answer remains ordinary conversation history. The inspection
adapter forbids identification, sensitive-trait inference, and admission judgments from
appearance. For display, the tool returns an opaque `applicant://{application_id}/photo`
reference rather than a path or public URL. The trusted browser maps that reference to an
authenticated instructor-only endpoint; anonymous, student, TA, and admin requests receive
the same `404`, and successful responses use `Cache-Control: private, no-store`.

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

Production backups must cover PostgreSQL, shared course storage, and the private
applicant directory. Temporary uploads normally remain outside backups. Periodically
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

## PostgreSQL integration tests

Set `TEST_DATABASE_URL` to a disposable development PostgreSQL database and run `uv run pytest -m postgres`. Tests create a random isolated schema and drop that schema afterward. They do not modify the database's public schema.
