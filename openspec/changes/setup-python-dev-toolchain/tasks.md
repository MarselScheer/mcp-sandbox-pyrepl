## 1. Dev Dependencies in pyproject.toml

- [x] 1.1 Add `[project.optional-dependencies] dev` group with `pytest>=8`, `pytest-cov>=5`, `ruff>=0.5`, `ty>=0.0.18`
- [x] 1.2 Add `[tool.pytest.ini_options]` with test paths, coverage config, and default flags
- [x] 1.3 Add `[tool.ruff]` sections for linting rules, formatting options, and target version
- [x] 1.4 Add `[tool.ty]` sections for type-checking rules and source paths

## 2. Makefile

- [x] 2.1 Create root-level `Makefile` with `.PHONY` targets: `install`, `test`, `lint`, `format`, `format-check`, `typecheck`, `check`, `clean`
- [x] 2.2 Wire `make install` to `uv sync --group dev`
- [x] 2.3 Wire `make test` to `uv run pytest -v --tb=short --cov=src tests/`
- [x] 2.4 Wire `make lint` to `uv run ruff check src/ tests/`
- [x] 2.5 Wire `make format` to `uv run ruff format src/ tests/`
- [x] 2.6 Wire `make format-check` to `uv run ruff format --check src/ tests/`
- [x] 2.7 Wire `make typecheck` to `uv run ty src/`
- [x] 2.8 Wire `make check` to run lint, then typecheck, then test (fast checks first)
- [x] 2.9 Wire `make clean` to remove `__pycache__`, `.ruff_cache/`, `.mypy_cache/`, `.pytest_cache/`, `htmlcov/`, `.coverage`

## 3. Tests Directory and Smoke Test

- [x] 3.1 Create `tests/__init__.py` (empty)
- [x] 3.2 Create `tests/test_toolchain.py` with smoke tests — verify pytest runs, ruff is importable, ty is importable
- [x] 3.3 Verify the toolchain works: `make check` passes

## 4. .gitignore Updates

- [x] 4.1 Add `__pycache__/`, `.ruff_cache/`, `.pytest_cache/`, `htmlcov/`, `.coverage`, `*.egg-info/` to `.gitignore`