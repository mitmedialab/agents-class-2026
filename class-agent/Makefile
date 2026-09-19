# Keep in sync with test-all.ps1 (Windows equivalent)
.PHONY: check python-check typescript-check e2e all

all: check e2e

check: python-check typescript-check

python-check:
	uv run ruff check python
	uv run ruff format --check python
	uv run mypy python/agent_core python/course_server python/runtime_smolagents python/tests
	uv run pytest

typescript-check:
	pnpm typecheck
	pnpm test
	pnpm build

# End-to-end browser tests — requires Node Playwright browsers installed:
#   pnpm exec playwright install --with-deps chromium
# Starts the Vite dev server automatically; no backend or DB needed.
e2e:
	pnpm test:e2e
