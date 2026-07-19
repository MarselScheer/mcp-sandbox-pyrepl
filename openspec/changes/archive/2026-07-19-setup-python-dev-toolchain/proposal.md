## Why

The project has source code (`src/`) with no testing, linting, formatting, or type-checking infrastructure. Without these, code quality is inconsistent, refactoring is risky, and there's no automated feedback loop for developers. Adding a standard Python toolchain — pytest, ruff, ty, and a Makefile — establishes a repeatable quality baseline and integrates with CI and IDE workflows.

## What Changes

- **Add `pytest`** as the test runner with `pytest-cov` for coverage reporting
- **Add `ruff`** for linting and formatting, replacing the need for separate flake8/black/isort tools
- **Add `ty`** for static type checking (a modern mypy-compatible type checker written in Rust)
- **Add a `Makefile`** at the project root with targets for all tools: `test`, `lint`, `format`, `typecheck`, `check` (all-in-one), `clean`
- **Update `pyproject.toml`** with tool configuration for pytest, ruff, and ty
- **Add a `tests/` directory** structure and a smoke test to verify the toolchain works
- **Add `pytest`, `ruff`, and `ty`** to project's dev dependencies (optional-dependencies in pyproject.toml)

## Capabilities

### New Capabilities

*None — this is a developer experience change, not a product capability. No new specs are needed.*

### Modified Capabilities

*None — no existing spec-level behavior is changing.*

## Impact

- **`pyproject.toml`**: Add tool configuration sections for `pytest`, `ruff`, `ty`; add `[project.optional-dependencies] dev` group
- **New file `Makefile`**: Root-level Makefile with targets: `test`, `lint`, `format`, `typecheck`, `check`
- **New directory `tests/`**: Test structure with `tests/__init__.py` and a smoke test for the toolchain
- **`.gitignore`**: Update if needed to exclude `.ruff_cache/`, `htmlcov/`
- **Developer workflow**: Running `make check` before commits will be the standard workflow