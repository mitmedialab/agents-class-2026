.PHONY: check python-check typescript-check

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
