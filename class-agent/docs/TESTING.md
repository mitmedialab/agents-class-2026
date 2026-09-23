# Testing Guide

This document explains every test layer in the Class Agent platform, how to run
them locally, and how to extend them for new features or flows.

---

## Overview

The test suite has three independent layers, each at a different altitude:

| Layer | Tool | What it covers | Backend needed? |
|---|---|---|---|
| Python unit + contract | pytest | Auth, API routes, stable contracts, tool authorization, mail workflow | No (in-memory / SQLite) |
| TypeScript unit + component | Vitest + React Testing Library | Protocol types, workspace reducer, React components, App interaction | No (mocked API) |
| Browser end-to-end | Playwright | Full browser flows: splash, login, workspace UI, agent streaming | No (API mocked at network layer) |

Run all three from `class-agent/` before submitting:

```bash
make -k all      # run every layer, collect all failures, report at end (recommended)
make all         # same, but stops at first failure
make check       # Python lint + types + pytest, TS typecheck + Vitest + Vite build (no browser)
make e2e         # Playwright browser tests only
```

> **Note**: the known jsdom Calendar failure in `Viewers.test.tsx` causes `pnpm test`
> to exit non-zero. Without `-k`, `make all` stops there and the E2E suite does not
> run. Use `make -k all` to run all three layers regardless of earlier failures.

---

## Python tests (pytest)

### Setup

```bash
# From class-agent/
uv sync                   # creates .venv and installs all deps
docker-compose up -d postgres   # only needed for postgres-marked tests
cp -n .env.example .env   # copy env template once
```

### Running

```bash
uv run pytest                         # all non-postgres tests (fast, no DB required)
uv run pytest -m postgres             # DB integration tests (needs TEST_DATABASE_URL)
uv run pytest python/tests/test_auth_security.py   # single file
uv run pytest -k "test_access_code"   # keyword filter
```

Set `TEST_DATABASE_URL` to enable PostgreSQL tests:

```bash
export TEST_DATABASE_URL=postgresql://class_agent:class_agent_dev@127.0.0.1:5432/class_agent
uv run pytest -m postgres
```

Each DB integration test creates and destroys a uniquely named schema; it never
truncates the public schema.

### What is tested

- **Auth security** (`test_auth_security.py`): Argon2id hashing, access code entropy, session token isolation
- **Auth service** (`test_auth_service.py`): login/logout flow, rate limiting, session revocation
- **Course resources** (`test_course_resources.py`): public resource serving, role-scoped visibility
- **Workspace** (`test_workspace.py`): command validation, unknown-component rejection, prop schema checks
- **FastAPI routes** (`test_fastapi_api.py`): agent run, conversation creation, workspace actions, TA flow
- **Models** (`test_models.py`): Event serialization round-trips, PrincipalContext construction
- **Mail workflow** (`test_mail.py`): TA question creation, PUBLISH/PRIVATE decision parsing
- **Authorization cases**: positive and negative role/ownership checks throughout

### Writing new tests

Follow the nearest existing test in `python/tests/` as the extension point. Key rules:

- Do not call external model APIs from tests; use the `RecordingRuntime` mock or inject a scripted provider.
- Do not truncate shared databases; use uniquely named schemas or in-memory stores.
- Every authorization change needs at least one positive case and one negative case.
- Use the `InMemory*` store implementations from `course_server` for non-DB tests.

---

## TypeScript tests (Vitest + React Testing Library)

### Setup

```bash
# From class-agent/
pnpm install
```

### Running

```bash
pnpm test                          # all packages in parallel
pnpm --filter @class-agent/web test        # web app only
pnpm --filter @class-agent/protocol test   # protocol contracts
pnpm --filter @class-agent/workspace test  # workspace reducer
pnpm --filter @class-agent/web exec vitest run src/App.test.tsx   # single file
```

### What is tested

- **`packages/protocol`** (`test/contracts.test.ts`): 13 contract-serialization tests covering every stable wire type.
- **`packages/workspace`** (`test/registry.test.ts`): 8 tests covering component registry lookups and workspace command validation.
- **`apps/web/src/App.test.tsx`**: 31 tests covering the full `App` component surface — splash screen, conversation management, login, workspace events, TA confirmation, file upload, streaming, and shortcuts.
- **`apps/web/src/Viewers.test.tsx`**: 27 tests for DocumentViewer, DraftDocument, Calendar, WebpageViewer, and BrowserViewer rendering and interactions.
- **`apps/web/src/api.test.ts`**: 7 tests for API client SSE parsing and error handling.

**Known pre-existing issue**: `Viewers.test.tsx > Calendar > parses every row in the
published schedule source` fails in jsdom because the Calendar component does not
attach `role="gridcell"` aria-labels in a headless environment. All other 75 tests pass.
This does not affect the Playwright tests where a real Chromium browser renders the
component correctly.

### Writing new tests

- Add component tests in the package nearest to the component: `packages/ui/` for
  primitives, `apps/web/src/` for product-level behaviour.
- Use the `vi.mock("./api.js", ...)` pattern from `App.test.tsx` for API isolation.
- Interaction tests require accessibility assertions (role, label, state), not only
  CSS class or snapshot checks.
- Contract changes must include an update to `packages/protocol/test/contracts.test.ts`.

---

## Browser end-to-end tests (Playwright)

### Setup

Install the Playwright Chromium browser once (about 120 MB):

```bash
# From class-agent/
pnpm exec playwright install --with-deps chromium
```

No running backend is needed. Tests start the Vite dev server automatically
(`pnpm dev`) and intercept all `/api/v1/**` requests at the network layer using
`page.route()` fixtures.

### Running

```bash
pnpm test:e2e                 # headless, all specs, CI-friendly
pnpm test:e2e:headed          # show a visible browser window
pnpm test:e2e:ui              # interactive Playwright UI (step through tests)
make e2e                      # alias for pnpm test:e2e

# Single spec file
pnpm exec playwright test e2e/public-agent.spec.ts
# Single test by title
pnpm exec playwright test --grep "Schedule shortcut"
```

Playwright generates an HTML report in `playwright-report/` after each run:

```bash
pnpm exec playwright show-report
```

### Test architecture

All tests share two support files:

| File | Purpose |
|---|---|
| `e2e/fixtures.ts` | Static mock data (principal contexts, conversations, SSE stream helpers) |
| `e2e/setup.ts` | `setupPublicRoutes` / `setupStudentRoutes` helpers that wire `page.route()` intercepts before `page.goto()` |

The `playwright.config.ts` at the root of `class-agent/`:

- Points `testDir` at `./e2e/`
- Starts `pnpm dev` as the web server (`webServer`)
- Sets `baseURL: "https://localhost:5173"` and `ignoreHTTPSErrors: true` (Vite dev server uses self-signed TLS via `@vitejs/plugin-basic-ssl`)
- Runs tests with a single worker in sequence (no parallel execution)

### What is tested

**`e2e/public-agent.spec.ts`** — CONSTITUTION §96 (public visitor flow)

| Test | Key assertions |
|---|---|
| Opening splash and interface reveal | Splash visible on load; `inert` attribute present; splash gone after 3.6 s; interface active |
| Welcome message and navigation shortcuts | `.latest-response` contains "Welcome"; MIT/MIT Media Lab/Apply/Schedule/Grading/About buttons visible |
| History drawer lists previous conversations | "Your logs" → "Week one" button appears |
| Open existing conversation | Clicking a conversation shows its last agent message |
| Create conversation from first message | Sending a typed message triggers POST to `/run/stream` |
| About / syllabus view | Clicking About loads syllabus heading and content; composer hidden; re-click dismisses |

**`e2e/student-login.spec.ts`** — CONSTITUTION §97 (authentication)

| Test | Key assertions |
|---|---|
| Login form inside history drawer | `Email or username`, `Access code`, `Log in` visible |
| Credential submission | POST payload has `username` + `access_code`; drawer closes on success |
| Public visitors lack student-only UI | No "Alice Example" or "alice" text visible |
| Drawer open/close | Dialog appears and disappears correctly |
| Authenticated student state | Student's conversations listed in drawer |

**`e2e/workspace-ui.spec.ts`** — CONSTITUTION §99 (dynamic workspace)

| Test | Key assertions |
|---|---|
| Schedule → Calendar panel | Workspace complementary region appears; Apply shortcut hidden while workspace open |
| Close workspace panel | Panel closes; Apply button reappears |
| Composer disabled during run | Composer becomes `disabled` immediately after pressing Enter |
| Streamed agent reply | `.latest-response` shows streamed text; composer re-enabled |
| MIT logo resets conversation | Composer cleared; welcome message re-shown with `data-staggered` |

### SSE mock format

`textSseStream(text)` and `calendarSseStream(text)` in `e2e/fixtures.ts` produce valid
Server-Sent Event bodies that `streamAgentRun` in `api.ts` parses correctly. For a
new event type, add a helper in `fixtures.ts` that follows the same `event: platform`
format documented in `docs/EVENTS.md`.

### Writing new E2E tests

1. Create a new `.spec.ts` file under `e2e/`.
2. Call `await setupPublicRoutes(page)` or `await setupStudentRoutes(page)` at the top
   of each test (or in a `test.beforeEach`).
3. Override specific routes with `await page.route(...)` after setup to inject
   feature-specific responses.
4. Follow the naming convention in `fixtures.ts` for new mock data constants.
5. Add the new flow to the coverage tables above.

**Adding a new workspace component test**

```typescript
// Override the stream route to return a workspace.panel.opened event
await page.route("**/api/v1/conversations/*/run/stream", (route) =>
  route.fulfill({
    status: 200,
    headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" },
    body: [
      "event: platform",
      `data: ${JSON.stringify({
        type: "workspace.panel.opened",
        event: {
          payload: {
            command: {
              type: "open",
              panel: {
                id: "40000000-0000-4000-8000-000000000099",
                component_id: "your-new-component",
                title: "My Panel",
                props: { /* validated props */ },
                state: {},
              },
            },
          },
        },
      })}`,
      "",
      "event: message",
      `data: ${JSON.stringify({ type: "agent.text.done", text: "Panel is open." })}`,
      "",
      "event: done",
      `data: {}`,
      "",
      "",
    ].join("\n"),
  }),
);
```

---

## CI integration

The project uses no CI configuration file yet. Below is a reference GitHub Actions
workflow that runs all three test layers:

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  typescript:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: class-agent
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with:
          version: 10
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: pnpm
          cache-dependency-path: class-agent/pnpm-lock.yaml
      - run: pnpm install
      - run: pnpm typecheck
      - run: pnpm test
      - run: pnpm build

  python:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: class-agent
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync
      - run: uv run ruff check python
      - run: uv run ruff format --check python
      - run: uv run mypy python/agent_core python/course_server python/runtime_smolagents python/tests
      - run: uv run pytest

  e2e:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: class-agent
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with:
          version: 10
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: pnpm
          cache-dependency-path: class-agent/pnpm-lock.yaml
      - run: pnpm install
      - run: pnpm exec playwright install --with-deps chromium
      - run: pnpm test:e2e
      - uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: playwright-report
          path: class-agent/playwright-report/
          retention-days: 7
```

The E2E job is intentionally separate from the TypeScript job. Its `CI=true`
environment variable triggers:
- Retries on flaky tests (up to 2 retries per test)
- `github` reporter format for inline PR annotations
- The web server is started fresh (`reuseExistingServer: false`)

### Running the postgres job in CI

Add a `postgres` service and set `TEST_DATABASE_URL`:

```yaml
  postgres-tests:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: class_agent
          POSTGRES_USER: class_agent
          POSTGRES_PASSWORD: class_agent_dev
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    defaults:
      run:
        working-directory: class-agent
    env:
      TEST_DATABASE_URL: postgresql://class_agent:class_agent_dev@127.0.0.1:5432/class_agent
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync
      - run: uv run python -m course_server.migrations apply
      - run: uv run pytest -m postgres
```

---

## Summary of test file locations

```text
class-agent/
├── playwright.config.ts         Playwright configuration
├── e2e/
│   ├── fixtures.ts              Shared mock data and SSE helpers
│   ├── setup.ts                 page.route() setup helpers
│   ├── public-agent.spec.ts     §96 Public visitor flow
│   ├── student-login.spec.ts    §97 Student authentication
│   └── workspace-ui.spec.ts     §99 Dynamic workspace UI
├── python/tests/
│   └── test_*.py                pytest unit and integration tests
├── packages/
│   ├── protocol/test/           Contract serialization tests
│   └── workspace/test/          Workspace reducer and registry tests
└── apps/web/src/
    ├── App.test.tsx              Full App integration tests
    ├── Viewers.test.tsx          Component rendering tests
    ├── api.test.ts               API client tests
    └── test/setup.ts             jsdom + jest-dom setup
```
