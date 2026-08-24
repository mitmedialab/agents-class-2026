# Server storage

PostgreSQL stores durable server-side identity and canonical conversation history. Raw access codes and raw session tokens are never stored, and no smolagents objects are persisted.

## Tables

- `schema_migrations`: immutable applied version/checksum records;
- `users`: user profile, role, active state, and Argon2id access-code hash;
- `auth_sessions`: hashed authenticated tokens and revocation/expiry metadata;
- `anonymous_sessions`: hashed temporary public-session tokens and expiry metadata;
- `auth_login_failures`: hashed rate-limit keys and timestamps.
- `conversations`: one explicitly user- or anonymous-session-owned conversation;
- `events`: canonical JSON event envelopes with JSONB payload and metadata.

Conversation messages are represented by `user.message` and `agent.message` events. The database does not store a smolagents agent, memory object, pickle, or provider-specific conversation object.

Later-phase tables from the constitution are added only when their owning application feature is implemented.

## Migrations

Apply migrations with:

```bash
uv run python -m course_server.migrations apply
```

Migration filenames are ordered and checksummed. Never edit an applied migration; add a new migration instead. The runner refuses to continue if a committed migration differs from the checksum recorded by a database.

## Backups

Example backup and restore commands:

```bash
pg_dump --format=custom --file=class-agent.dump "$DATABASE_URL"
createdb class_agent_restored
pg_restore --dbname=class_agent_restored class-agent.dump
```

Production backups must cover PostgreSQL and, in later phases, shared course storage. Periodically test restoration rather than assuming a backup file is usable.

## PostgreSQL integration tests

Set `TEST_DATABASE_URL` to a disposable development PostgreSQL database and run `uv run pytest -m postgres`. Tests create a random isolated schema and drop that schema afterward. They do not modify the database's public schema.
