# Local setup for student forks

The fork does not include the operational course roster. This setup creates two
fictional students, Ada Example and Bo Sample, their protected roster resources,
and matching local login accounts. It uses no real student records or GitHub repos.
It does not prescribe an assignment or a memory strategy.

From `class-agent/` in a fresh fork, after installing the tools listed in the
[main README](../../README.md):

```bash
uv sync
pnpm install
docker compose up -d postgres
uv run python examples/memory_starter/setup.py
```

The last command creates the ignored local data and `.env` file, applies database
migrations, indexes public course resources, and prints a one-time access code for
each fictional student. Save those codes locally; do not commit them. The setup is
safe to rerun with the same fixture and refuses to replace an existing real roster.
Use `--data-only --output-root /path/to/empty/directory` to try the file setup without
connecting to PostgreSQL. A non-default local database may be passed with
`--database-url`; remote database URLs are refused.

Add your own `OPENAI_API_KEY` to `.env` for live agent conversations. Then use two
terminals:

```bash
uv run python -m course_server.api
pnpm dev
```

Open **https://localhost:5173** and accept the local development certificate warning.
Vite already supplies HTTPS and proxies `/api` to the local server. Log in as either
fictional student to develop, and use the second account to check user separation.
The default Python tests use scripted models and do not require an API key.

The setup deliberately leaves GitHub integration disabled. If a project needs real
repository context, use your own repo in your local experiment. Do not commit private
tokens or collected user profiles to the fork.
