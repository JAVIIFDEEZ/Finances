# InvestingLab — task runner.
#
# `just` itself is pinned in uv.lock (package `rust-just`), so after `uv sync` every
# recipe is available as `uv run just <recipe>` (or plain `just` if installed globally).

set dotenv-load := false
set shell := ["bash", "-euo", "pipefail", "-c"]

core := "packages/investinglab"

# List the available recipes.
default:
    @just --list --unsorted

# ── Setup ─────────────────────────────────────────────────────────────

# Install every dependency group and the git hooks.
setup:
    uv sync --all-groups
    uv run pre-commit install --install-hooks --hook-type pre-commit --hook-type commit-msg

# ── Quality gates ─────────────────────────────────────────────────────

# Run every gate that CI runs: lint, typecheck and tests.
check: lint typecheck test

# Lint, verify formatting and enforce the architecture contracts.
lint:
    uv run ruff check .
    uv run ruff format --check .
    uv run lint-imports

# Apply automatic lint fixes and format the code.
fmt:
    uv run ruff check --fix .
    uv run ruff format .

# Static type checking (mypy --strict).
typecheck:
    uv run mypy

# Run the test suite with coverage. Extra pytest arguments are forwarded.
test *args:
    uv run pytest --cov --cov-report=term-missing {{ args }}

# Run the tests without coverage, stopping at the first failure.
test-fast *args:
    uv run pytest -x -q {{ args }}

# Run every pre-commit hook against the whole repository.
hooks:
    uv run pre-commit run --all-files

# Record real provider responses as test cassettes (optionally only names containing a text).
record-fixtures *only:
    uv run python scripts/record_fixtures.py {{ only }}

# ── Applications ──────────────────────────────────────────────────────

# Serve the REST API with live reload (http://127.0.0.1:8000/docs).
api:
    uv run investinglab-api --reload

# Write the API contract (OpenAPI) and regenerate the web client's types from it.
openapi:
    uv run investinglab-api --openapi apps/api/openapi.json
    cd apps/web && pnpm api:types

# Install the web app's dependencies (Node 22 and pnpm).
web-install:
    cd apps/web && pnpm install

# Serve the web app with live reload (http://localhost:3000; needs the API).
web:
    cd apps/web && pnpm dev

# Lint, typecheck, unit-test and build the web app.
web-check:
    cd apps/web && pnpm lint && pnpm typecheck && pnpm test && pnpm build

# End-to-end tests: offline API over synthetic data and the built web app.
web-e2e:
    cd apps/web && pnpm build && pnpm e2e --trace off

# Run the API and the web app together: open http://localhost:3000 (Ctrl+C stops both).
dev:
    #!/usr/bin/env bash
    set -euo pipefail
    [ -d apps/web/node_modules ] || (cd apps/web && pnpm install)
    trap 'kill 0' EXIT INT TERM
    uv run investinglab-api --reload &
    (cd apps/web && pnpm dev) &
    wait

# ── Documentation ─────────────────────────────────────────────────────

# Serve the documentation site with live reload.
docs:
    uv run zensical serve

# Build the documentation site into ./site.
docs-build:
    uv run zensical build --clean

# Regenerate the traceability matrices of the master's modules (docs/modules/).
traceability:
    uv run python -m investinglab.modules docs/modules

# ── Housekeeping ──────────────────────────────────────────────────────

# Remove caches and build artefacts.
clean:
    rm -rf .mypy_cache .ruff_cache .pytest_cache .hypothesis .coverage coverage.xml htmlcov site dist
    find . -type d -name __pycache__ -prune -exec rm -rf {} +
