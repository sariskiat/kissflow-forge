.PHONY: test test-coverage test-live lint format architecture verify start

test:
	uv run pytest

test-coverage:
	uv run pytest --cov=src/app --cov-report=term-missing   # fails under 89% (pyproject)

# Hits the REAL Kissflow dev tenant via KF_APP. Never part of `make verify`.
test-live:
	uv run pytest --run-live -q \
	  tests/test_live_lifecycle.py tests/test_live_branching.py tests/test_live_template_app.py

lint:
	uv run ruff format --check .
	uv run ruff check .
	uv run lint-imports
	uv run ty check .

architecture:
	uv run lint-imports

format:
	uv run ruff check --fix .
	uv run ruff format .

verify: lint test

start:
	uv run mcp-server
