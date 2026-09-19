# agents-class-2026

The Course Agent platform lives in [`class-agent/`](class-agent/). Its
[`CONSTITUTION.md`](class-agent/CONSTITUTION.md) is the architectural source of truth.

All human and AI-assisted contributions must follow [`AGENTS.md`](AGENTS.md), the scoped
instructions beneath `class-agent/`, and
[`class-agent/CONTRIBUTING.md`](class-agent/CONTRIBUTING.md).

## Testing

The platform has three independent test layers. All three run from the `class-agent/`
directory. See "Run all tests" below for the one-command entry point on your OS.

### Prerequisites

All platforms need the following tools:

| Tool | Purpose | Install |
|---|---|---|
| [`uv`](https://docs.astral.sh/uv/getting-started/installation/) | Python package manager | `curl -LsSf https://astral.sh/uv/install.sh \| sh` (macOS/Linux) or [astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) (Windows) |
| [`pnpm`](https://pnpm.io/installation) | Node package manager | `npm install -g pnpm` |
| Node ≥ 20 | JavaScript runtime | `nvm install 20` or [nodejs.org](https://nodejs.org) |

**macOS** additionally needs `make`, which comes with Xcode Command Line Tools:

```bash
xcode-select --install
```

**Linux** ships with `make` by default.

**Windows** uses a PowerShell script instead — no extra tool needed.

### One-time setup

```bash
cd class-agent

# Install Python dependencies
uv sync

# Install Node dependencies
pnpm install

# Install Playwright's Chromium browser (~120 MB, needed for E2E tests)
pnpm exec playwright install --with-deps chromium
```

### Run all tests

**macOS / Linux** — using `make`:

```bash
cd class-agent
make -k all
```

**Windows** — using the PowerShell script:

Open **PowerShell** (not Command Prompt, not by double-clicking the file), then:

```powershell
cd class-agent
powershell -ExecutionPolicy Bypass -File .\test-all.ps1
```

> **First time only**: Windows blocks unsigned scripts by default. If you'd rather not
> pass `-ExecutionPolicy Bypass` every time, run this once in PowerShell as your user:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```
> After that, `.\test-all.ps1` works directly from any PowerShell terminal.

Both run Python → TypeScript → Playwright in sequence, collect every failure, and
report them all at the end. Exit code is non-zero if anything failed.

### Python unit and contract tests (pytest)

```bash
cd class-agent
uv run pytest                          # all non-postgres tests
uv run pytest -m postgres              # requires TEST_DATABASE_URL
```

Covers authentication security, stable contract serialization, authorization rules,
API route behaviour, workspace validation, and mail-workflow logic. External model
calls are mocked; no OpenAI credits are spent. See
[`class-agent/docs/TESTING.md`](class-agent/docs/TESTING.md) for full details.

### TypeScript unit and component tests (Vitest + React Testing Library)

```bash
cd class-agent
pnpm test
```

Covers protocol contracts, workspace reducer logic, component rendering, API
streaming, and the full `App` interaction surface through mocked API calls.
31 App tests, 13 protocol/workspace/viewer tests.

Known pre-existing issue: one Calendar viewer test (`Viewers.test.tsx: parses every
row in the published schedule source`) fails in jsdom because the calendar grid does
not attach the expected `gridcell` aria-labels in a headless environment. All other
75 tests pass.

### Browser end-to-end tests (Playwright)

```bash
cd class-agent
pnpm exec playwright install --with-deps chromium   # first time only
pnpm test:e2e                                        # headless Chromium
pnpm test:e2e:headed                                 # watch mode
pnpm test:e2e:ui                                     # interactive Playwright UI
make e2e                                             # macOS / Linux shorthand
```

16 tests across three spec files cover the flows specified in CONSTITUTION §96–99:
- `e2e/public-agent.spec.ts` — public visitor experience (§96): splash screen,
  welcome message, navigation shortcuts, conversation history, syllabus view
- `e2e/student-login.spec.ts` — student authentication (§97): login form,
  credential submission, drawer open/close
- `e2e/workspace-ui.spec.ts` — dynamic workspace UI (§99): Schedule→Calendar
  panel, panel close, streamed agent replies, composer disabled during run

Tests intercept all API calls at the network layer so no running backend is needed.
The Vite dev server is started automatically. See
[`class-agent/docs/TESTING.md`](class-agent/docs/TESTING.md) for CI integration
and how to extend the suite for new features.
