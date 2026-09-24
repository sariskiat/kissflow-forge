.PHONY: test test-coverage test-live lint format architecture verify start

test:
	uv run pytest

test-coverage:
	uv run pytest --cov=src/app --cov-report=term-missing   # fails under 90% (pyproject)

# Hits the REAL Kissflow dev tenant via KF_APP. Never part of `make verify`.
test-live:
	uv run pytest --run-live -q \
	  tests/integration/test_live_lifecycle.py tests/integration/test_live_branching.py \
	  tests/integration/test_live_template_app.py tests/integration/test_live_page_plan.py

lint:
	uv run ruff format --check .
	uv run ruff check .
	uv run lint-imports
	# The clone keeps ty's import root at src; tests need explicit search paths for their fakes.
	uv run ty check . --extra-search-path . --extra-search-path tests

architecture:
	uv run lint-imports

format:
	uv run ruff check --fix .
	uv run ruff format .

verify: lint
	uv run pytest --cov=src/app --cov-fail-under=90 -q

start:
	uv run mcp-server
