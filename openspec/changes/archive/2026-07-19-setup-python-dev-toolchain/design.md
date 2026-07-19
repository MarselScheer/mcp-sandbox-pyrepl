## Context

The project currently has no development tooling — no test runner, no linter, no formatter, no type checker. Code is written in `src/` with a bare `pyproject.toml` that only defines runtime dependencies. The existing `docker-ide/Makefile` provides Docker workflow targets but no Python tooling targets.

The developer experience needs a standard set of tools that:
- Run locally (not inside Docker) for fast feedback
- Integrate with CI pipelines
- Follow a consistent command pattern via a root-level Makefile
- Are configured in a single source of truth (`pyproject.toml`)

## Goals / Non-Goals

**Goals:**
- Provide `pytest` with coverage reporting as the test framework
- Provide `ruff` for both linting and formatting (single dependency, no separate flake8/black/isort)
- Provide `ty` for static type checking
- Provide a `Makefile` with consistent targets: `test`, `lint`, `format`, `typecheck`, `check`, `clean`
- Configure all tools in `pyproject.toml` where possible
- Add a `tests/` directory with a smoke test that validates the toolchain works
- Add dev dependencies to `[project.optional-dependencies] dev` so they can be installed with `pip install -e ".[dev]"` or `uv sync --group dev`

**Non-Goals:**
- Running tests inside Docker (CI will use the same Python environment)
- Adding pre-commit hooks (left for a future change)
- Configuring coverage thresholds (left for a future change)
- Modifying the existing `docker-ide/Makefile`
- Adding CI configuration files (GitHub Actions, etc.)
- Performance optimization of test suite (no tests exist yet)

## Decisions

### Decision 1: uv over pip for dev dependency management
**Chosen:** Use `uv` as the package manager, consistent with the project's existing `[tool.uv]` section in `pyproject.toml`.

Dev dependencies go in `[project.optional-dependencies] dev` in `pyproject.toml`. Developers run `uv sync --group dev` to install everything. The Makefile will include this as a dependency for all targets.

### Decision 2: ruff for both linting and formatting
**Chosen:** `ruff check` for linting, `ruff format` for formatting.

Ruff is fast (Rust-based), replaces flake8 + isort + black in a single dependency, and is already from the same ecosystem as `uv` and `ty` (Astral). Configuration goes in `[tool.ruff]` sections in `pyproject.toml`.

### Decision 3: ty for type checking
**Chosen:** `ty` from Astral (same team as ruff and uv).

`ty` is a Rust-based type checker that is compatible with mypy's type system but significantly faster. It's designed to be a drop-in replacement with better performance. Configuration goes in `[tool.ty]` sections in `pyproject.toml`.

### Decision 4: Makefile with phony targets
**Chosen:** A GNU Makefile at the project root with `.PHONY` declarations.

Targets:
- `make install` — `uv sync --group dev` (install all dependencies including dev)
- `make test` — `uv run pytest` with coverage
- `make lint` — `uv run ruff check src/ tests/`
- `make format` — `uv run ruff format src/ tests/`
- `make format-check` — `uv run ruff format --check src/ tests/` (for CI)
- `make typecheck` — `uv run ty src/`
- `make check` — runs lint, typecheck, test (ordered: fast checks first)
- `make clean` — remove cache directories, coverage artifacts

### Decision 5: pytest configuration in pyproject.toml
**Chosen:** `[tool.pytest.ini_options]` in `pyproject.toml`.

Test discovery path: `tests/`. Add `pytest-cov` for coverage reporting. Default flags: `-v --tb=short --cov=src`.

### Decision 6: Tests directory structure
**Chosen:** Flat `tests/` directory with `tests/__init__.py` and test files matching `test_*.py`.

A smoke test (`tests/test_toolchain.py`) will verify that pytest, ruff, and ty are importable and runnable. This validates the dev environment is set up correctly.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| **`ty` is a newer tool** — may have fewer docs or missing features compared to mypy | `ty` is compatible with mypy's type system; if gaps appear, the Makefile can be updated to swap to mypy with minimal effort |
| **`ruff format` is not PEP 8 compliant in edge cases** — ruff intentionally diverges from black's formatting in some areas | This is acceptable; ruff's formatting is opinionated and consistent. If the team prefers black, the Makefile target can be swapped |
| **`uv` may not be installed** — not all developers will have uv | Document `pip install uv` in the README; the Makefile can check for uv availability |
| **Tool version drift** — CI and local environments may use different tool versions | Pin tool versions in `[project.optional-dependencies] dev` with `>=` bounds; CI can use `uv lock` for reproducibility |