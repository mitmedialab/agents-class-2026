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
- `faq_entries`: individually addressable active and inactive FAQ records.

Conversation messages are represented by `user.message` and `agent.message` events. The database does not store a smolagents agent, memory object, pickle, or provider-specific conversation object.

Later-phase tables from the constitution are added only when their owning application feature is implemented.

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

## PostgreSQL integration tests

Set `TEST_DATABASE_URL` to a disposable development PostgreSQL database and run `uv run pytest -m postgres`. Tests create a random isolated schema and drop that schema afterward. They do not modify the database's public schema.
