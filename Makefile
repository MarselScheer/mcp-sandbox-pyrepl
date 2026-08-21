.PHONY: install test test-integration lint format format-check typecheck check clean build-image

install:
	uv sync --group dev

test:
	uv run pytest -v --tb=short --cov=src tests/

test-integration:
	uv run pytest -v --tb=short -m integration tests/

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
