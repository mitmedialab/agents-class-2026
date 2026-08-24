# Class Agent

Class Agent is the extensible Course Agent platform described in [CONSTITUTION.md](CONSTITUTION.md). It is designed for an MIT Media Lab course and favors explicit, portable contracts that students can inspect and extend.

The repository is currently at **Phase 5**: a React/Vite interface over the Course Agent service. It contains stable core contracts, access-code and anonymous authentication, portable PostgreSQL conversation/event history, a `ToolCallingAgent` adapter, one public syllabus tool/resource, secure session-cookie routes, conversation APIs, Server-Sent Event output, and a minimal conversation/workspace frontend. It intentionally does not yet contain the phase-6 course resource catalog, dynamic workspace components, MCP servers, Agent Bridge, or a browser extension.

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
```

Put your key in `.env` as one unquoted, single-line assignment and leave `.env` uncommitted. Do not add literal `\\n` characters. Blank lines between assignments are fine:

```dotenv
OPENAI_API_KEY=your-key-here
MODEL_ID=gpt-5.6-terra
```

The CLI intentionally does not override variables already exported in the shell. If you previously exported an old key, run `unset OPENAI_API_KEY MODEL_API_KEY` so `.env` is used. Then run one CLI turn:

```bash
uv run python -m course_server.agent_cli "What does the syllabus say?"
```

Run the Phase 4 API at `http://127.0.0.1:8000` with:

```bash
uv run python -m course_server.api
```

In another terminal, run the Phase 5 web app:

```bash
pnpm dev
```

Vite serves the interface at `http://localhost:5173` and proxies `/api` to the
development API. Click the centered `Course Agent` title to open login and
conversation navigation. The default production build uses same-origin
`/api/v1`; set `VITE_API_BASE_URL` only when deploying the API elsewhere.

The API's session cookies are always marked `Secure`, including in development. A browser must therefore access it through HTTPS to retain sessions; terminating local TLS at a development proxy is the closest production-equivalent setup. The API is documented at `/docs`, with canonical routes under `/api/v1`.

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
packages/ui/             first-party React primitives and design tokens
apps/web/                 static Vite Course Agent interface
shared/schemas/v1/       canonical JSON Schemas and shared examples
database/migrations/     permanent checksummed PostgreSQL migrations
docs/                    architecture and versioning decisions
```

See [docs/API.md](docs/API.md), [docs/RUNTIME.md](docs/RUNTIME.md), [docs/AUTH.md](docs/AUTH.md), and [docs/STORAGE.md](docs/STORAGE.md) for behavior and operational guidance. The default tests use a scripted model and do not spend OpenAI credits.
