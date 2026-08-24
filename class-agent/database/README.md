# Database

Permanent PostgreSQL migrations live in `migrations/` and are applied in filename order. Applied versions and SHA-256 checksums are recorded in `schema_migrations`; an applied migration must never be edited.

Start the development database and apply migrations:

```bash
docker compose up -d postgres
export DATABASE_URL=postgresql://class_agent:class_agent_dev@127.0.0.1:5432/class_agent
uv run python -m course_server.migrations apply
uv run python -m course_server.index_resources
```

Phase 2 creates authentication-owned tables, Phase 3 adds portable conversation history,
and Phase 6 adds `course_resources` and `faq_entries` with PostgreSQL GIN full-text
indexes. Later phases add their tables through new migration files.

Do not commit production data, production hashes, or real student records. Create development users through the admin CLI so access codes are generated and hashed correctly.
