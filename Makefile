.PHONY: install test lint format format-check typecheck check clean

install:
	uv sync --group dev

test:
	uv run pytest -v --tb=short --cov=src tests/

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