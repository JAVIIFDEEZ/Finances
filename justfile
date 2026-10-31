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

# ── Documentation ─────────────────────────────────────────────────────

# Serve the documentation site with live reload.
docs:
    uv run zensical serve

# Build the documentation site into ./site.
docs-build:
    uv run zensical build --clean

# ── Housekeeping ──────────────────────────────────────────────────────

# Remove caches and build artefacts.
clean:
    rm -rf .mypy_cache .ruff_cache .pytest_cache .hypothesis .coverage coverage.xml htmlcov site dist
    find . -type d -name __pycache__ -prune -exec rm -rf {} +
