.PHONY: install test test-unit test-integration test-integration-parallel lint format format-check typecheck check clean build-image

install:
	uv sync --group dev

test:
	uv run pytest -v --tb=short --cov=src --cov-report term-missing tests/unit tests/integration

# Fast unit tests only — no Docker needed.
# Designed for the TDD cycle: run after every code change.
test-unit:
	uv run pytest -v --tb=short --cov=src --cov-report term-missing tests/unit

# Diagnostic mode — runs integration tests serially with --durations=0 to
# show per-test timing breakdown. Use this when debugging specific test
# performance or investigating failures that may be affected by parallelism.
# Expected runtime: ~3m40s (down from ~5m25s baseline).
test-integration:
	uv run pytest -v --tb=short --durations=0 tests/integration

# Runs integration tests in parallel (class/module-level workers).
# Requires pytest-xdist (installed via `uv sync --group dev`).
# Container names are UUID-scoped so parallel workers never collide.
# Expected runtime: ~35s on a 12-core machine (down from 5m25s baseline).
test-integration-parallel:
	uv run pytest -v --tb=short -n auto tests/integration

lint:
	uv run ruff check src/ tests/

format:
	uv run ruff format src/ tests/

format-check:
	uv run ruff format --check src/ tests/

typecheck:
	uv run ty check src/

check: lint typecheck test

clean:
	rm -rf __pycache__/ .ruff_cache/ .mypy_cache/ .pytest_cache/ htmlcov/ .coverage

build-image:
	uv run docker build \
		-t sandbox-base:3.12 \
		-f images/sandbox-base/Dockerfile \
		--build-arg PYTHON_VERSION=3.12 \
		.
