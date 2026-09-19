# test-all.ps1 — Windows equivalent of `make -k all` (keep in sync with Makefile)
#
# Runs every test layer in sequence, collects all failures, and reports them at
# the end. Exit code is non-zero if any layer failed.
#
# Prerequisites (one-time):
#   uv sync
#   pnpm install
#   pnpm exec playwright install --with-deps chromium
#
# Usage (from class-agent/):
#   .\test-all.ps1

$ErrorActionPreference = 'Continue'
$failed = @()

function Step([string]$name, [scriptblock]$block) {
    Write-Host ""
    Write-Host "=== $name ===" -ForegroundColor Cyan
    & $block
    if ($LASTEXITCODE -ne 0) { $script:failed += $name }
}

# Python layer
Step "ruff lint"   { uv run ruff check python }
Step "ruff format" { uv run ruff format --check python }
Step "mypy"        { uv run mypy python/agent_core python/course_server python/runtime_smolagents python/tests }
Step "pytest"      { uv run pytest }

# TypeScript layer
Step "typecheck"   { pnpm typecheck }
Step "vitest"      { pnpm test }
Step "build"       { pnpm build }

# Browser E2E layer
Step "playwright"  { pnpm test:e2e }

Write-Host ""
if ($failed.Count -gt 0) {
    Write-Host "Failed steps: $($failed -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "All tests passed." -ForegroundColor Green
