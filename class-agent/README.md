# Class Agent

Class Agent is the extensible Course Agent platform described in [CONSTITUTION.md](CONSTITUTION.md). It is designed for an MIT Media Lab course and favors explicit, portable contracts that students can inspect and extend.

The repository is currently at **Phase 7**: validated native workspace components over the Phase 6 Course Agent. It contains stable core and workspace contracts, access-code and anonymous authentication, portable PostgreSQL conversation/event history, a `ToolCallingAgent` adapter, public course resources and search, private course applications, typed workspace tools, an event-derived panel workspace, visual compositions, a specific-artifact DocumentViewer, and a month/agenda Calendar. It intentionally does not yet contain MCP Apps, Agent Bridge, or a browser extension.

## Requirements

- Python 3.11 or newer
- Node.js 20 or newer
- pnpm 10
- [uv](https://docs.astral.sh/uv/) for Python environments and commands
- Docker with Compose for the reference development PostgreSQL service

## Setup

On macOS, install the development tools with Homebrew and start the Colima Docker runtime:

```bash
brew install uv node pnpm docker docker-compose colima
colima start
docker version
docker-compose version
```

If Docker reports `docker-credential-desktop` is missing after switching from Docker Desktop, remove the stale `"credsStore": "desktop"` entry from `~/.docker/config.json`, then retry the pull.

From the repository root:

```bash
uv sync
pnpm install
docker-compose up -d postgres
cp -n .env.example .env
export DATABASE_URL=postgresql://class_agent:class_agent_dev@127.0.0.1:5432/class_agent
uv run python -m course_server.migrations apply
uv run python -m course_server.index_resources
```

Put your key in `.env` as one unquoted, single-line assignment and leave `.env` uncommitted. Do not add literal `\\n` characters. Blank lines between assignments are fine:

```dotenv
OPENAI_API_KEY=your-key-here
BRAVE_API_KEY=your-brave-search-key-here
MODEL_ID=gpt-5.6-terra
```

Anonymous visitors are limited for the lifetime of their seven-day session. The production
defaults are three conversations, ten agent runs, five uploads, and 20 MiB of uploads. Tune
`ANONYMOUS_MAX_CONVERSATIONS`, `ANONYMOUS_MAX_AGENT_RUNS`, `ANONYMOUS_MAX_UPLOADS`, and
`ANONYMOUS_MAX_UPLOAD_BYTES` in `.env`; authenticated users are exempt. Local development can
set `ANONYMOUS_QUOTAS_ENABLED=false`, but deployed environments should keep it enabled.
Production should also
enforce the per-IP limits in `deploy/cognitive-agents.nginx` because browser cookies can be reset.

The CLI intentionally does not override variables already exported in the shell. If you previously exported an old key, run `unset OPENAI_API_KEY MODEL_API_KEY BRAVE_API_KEY` so `.env` is used. Then run one CLI turn:

```bash
uv run python -m course_server.agent_cli "What does the syllabus say?"
```

Run the API at `http://127.0.0.1:8000` with:

```bash
uv run python -m course_server.api
```

The runtime prompt, authorized tool catalog, and public resource index are constructed
at API startup. Restart this process after changing Python runtime behavior or resource
manifests. Public resource file contents themselves are read when a tool is called.

In another terminal, run the web app:

```bash
pnpm dev
```

Vite serves the interface at `http://localhost:5173` and proxies `/api` to the
development API. Click the centered `Course Agent` title to open login and
conversation navigation. The default production build uses same-origin
`/api/v1`; set `VITE_API_BASE_URL` only when deploying the API elsewhere.

The API's session cookies are always marked `Secure`, including in development. A browser must therefore access it through HTTPS to retain sessions; terminating local TLS at a development proxy is the closest production-equivalent setup. The API is documented at `/docs`, with canonical routes under `/api/v1`. Public resource metadata is available at `/api/v1/course/resources`; the schedule is marked `provisional` until its details are confirmed.

Chat attachments are stored for 24 hours under `UPLOAD_DATA_PATH` (default
`var/uploads/`). Complete course applications submitted through the agent are written
as private structured records with a durable photo under `APPLICANT_DATA_PATH` (default
`var/applicants/`). Both directories are ignored by Git; only the applicant directory
normally belongs in protected production backups. See
[docs/COURSE_RESOURCES.md](docs/COURSE_RESOURCES.md) for resource manifests, automatic
indexing, uploads, and application-storage operations.

Role-scoped course resources live under `COURSE_DATA_PATH` (default `data/`): student
resources are available to logged-in students and instructors, while instructor resources
are available only to instructors. Their contents are ignored by Git and are never added to
the public registry or PostgreSQL public search index.

Run the real PostgreSQL integration test with:

```bash
export TEST_DATABASE_URL=postgresql://class_agent:class_agent_dev@127.0.0.1:5432/class_agent
uv run pytest -m postgres
```

## Checks

```bash
make check
```

Or run each tool independently:

```bash
uv run pytest
uv run ruff check python
uv run ruff format --check python
uv run mypy python/agent_core python/course_server python/runtime_smolagents python/tests
pnpm test
pnpm typecheck
```

## Current layout

```text
python/agent_core/       framework-independent Python contracts
python/course_server/    auth, orchestration, FastAPI/CLI, and PostgreSQL adapters
python/runtime_smolagents/ replaceable ToolCallingAgent/OpenAI adapters
python/tests/            Python serialization and contract tests
packages/protocol/       TypeScript wire-contract types and tests
packages/ui/             first-party React primitives, viewers, and design tokens
packages/workspace/      component manifests, workspace contracts, and reducer
apps/web/                 static Vite Course Agent interface
shared/schemas/v1/       canonical JSON Schemas and shared examples
database/migrations/     permanent checksummed PostgreSQL migrations
shared/course/            public course content and per-resource manifests
shared/registry/          public resource and trusted component registries
data/                     untracked role-scoped student and instructor resources
docs/                    architecture and versioning decisions
```

See [docs/API.md](docs/API.md), [docs/WORKSPACE.md](docs/WORKSPACE.md), [docs/RUNTIME.md](docs/RUNTIME.md), [docs/AUTH.md](docs/AUTH.md), and [docs/STORAGE.md](docs/STORAGE.md) for behavior and operational guidance. The default tests use a scripted model and do not spend OpenAI credits.

## Production hardening

The reference deployment files under `deploy/` provide TLS termination, security headers,
per-IP API/model rate and connection limits, a sandboxed systemd API service, and a conservative
SSH baseline. Follow `deploy/HARDENING.md` for firewall and SSH installation. Do not disable SSH
password authentication until a public key has been installed and verified in a separate session.
