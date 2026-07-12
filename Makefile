# Executable documentation. It cannot rot, because it breaks when it is wrong.

.PHONY: help setup dev test lint format check migrate down clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

setup:  ## Install dependencies (first run on a new machine)
	cd backend && uv sync
	cp -n backend/.env.example backend/.env || true
	@echo "Ready. Run 'make dev'."

dev:  ## Start Postgres, Redis and the API with hot reload
	docker compose up --build

down:  ## Stop everything
	docker compose down

test:  ## Run the test suite, including the tenant isolation checks
	cd backend && uv run pytest

lint:  ## Lint, format-check, verify architecture contracts and isolation guards
	cd backend && uv run ruff check .
	cd backend && uv run ruff format --check .
	cd backend && uv run lint-imports
	cd backend && uv run python scripts/check_forbidden_patterns.py

format:  ## Auto-fix formatting and import order
	cd backend && uv run ruff check --fix .
	cd backend && uv run ruff format .

check: lint test  ## Everything CI runs, locally

migrate:  ## Apply database migrations
	cd backend && uv run alembic upgrade head

clean:  ## Remove caches and the local database volume
	docker compose down -v
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf backend/.ruff_cache backend/.pytest_cache
