.DEFAULT_GOAL := help
SHELL := /bin/bash

PYTEST_ARGS ?=

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z0-9_-]+:.*##/ {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ------------------------------------------------------------------ setup
.PHONY: sync hooks-install
sync: ## Install dependencies (dev group)
	uv sync

hooks-install: ## Install git hooks: pre-commit checks + pre-push guard for main/develop
	uvx pre-commit install --hook-type pre-commit --hook-type pre-push

# ------------------------------------------------------------------ database
.PHONY: db-up db-up-durable db-down db-reset db-psql
db-up: ## Start the fast PostgreSQL test database (tmpfs, fsync off; port 26432)
	docker compose up -d --wait postgres

db-up-durable: ## Start PostgreSQL with default durability for measurements (port 26433)
	docker compose --profile durable up -d --wait postgres-durable

db-down: ## Stop the databases (the fast one is on tmpfs; the durable volume is kept)
	docker compose --profile durable down

db-reset: db-down db-up ## Recreate the test database

db-psql: ## psql shell on the test database
	docker compose exec postgres psql -U platina platina

# ------------------------------------------------------------------ quality
.PHONY: fmt lint typecheck guard agents-sync agents-check
fmt: ## Format and autofix (ruff)
	uv run ruff format .
	uv run ruff check --fix .

lint: ## ruff format --check + ruff check
	uv run ruff format --check .
	uv run ruff check .

typecheck: ## pyright (strict on src) + mypy --strict on src
	uv run pyright
	uv run mypy

guard: ## Architecture/test/language guards (import-linter + tools/guards)
	uv run lint-imports
	uv run python -m tools.guards

agents-sync: ## Regenerate .claude/.codex/.pi agent files from .agents/
	uv run python -m tools.agentsync

agents-check: ## Fail if generated agent files drifted from .agents/
	uv run python -m tools.agentsync --check

# ------------------------------------------------------------------ tests
.PHONY: test-unit test-unit-ft test-types test-int test
test-unit: ## Unit tests (no DB)
	uv run pytest tests/unit $(PYTEST_ARGS)

# Free-threaded CPython in its own environment (.venv-ft), so .venv keeps its interpreter.
FT_THREADS ?= 8
test-unit-ft: ## Unit tests on free-threaded 3.14t, FT_THREADS (8) threads per test; fails if the GIL is on
	UV_PROJECT_ENVIRONMENT=.venv-ft uv run --locked --python 3.14t \
		python -m tools.freethreaded tests/unit --parallel-threads $(FT_THREADS) $(PYTEST_ARGS)

test-types: ## Type tests: tests/typing/pass_* and fail_* under pyright AND mypy
	uv run python -m tools.typetests

test-int: ## Integration tests on real PostgreSQL (needs db-up)
	@if [ -n "$$(find tests/integration -name 'test_*.py' -print -quit 2>/dev/null)" ]; then \
		uv run pytest tests/integration $(PYTEST_ARGS); \
	else echo "test-int: no integration tests yet"; fi

test: test-unit test-types test-int ## Unit + type + integration tests

# ------------------------------------------------------------------ gates
.PHONY: check check-all
check: lint typecheck guard agents-check test-unit test-types ## Fast gate (no DB)

check-all: check test-unit-ft test-int ## Full gate: + free-threaded unit tests, integration (needs db-up)
