## Why

Coverage is currently calculated via `pytest-cov`, but the report only shows module-level percentages. Developers cannot see which specific lines are uncovered, making it harder to identify untested code that needs attention.

## What Changes

- Add `--cov-report term-missing` to pytest commands in the Makefile so the terminal output shows which line numbers are not covered in each module.
- Ensure all three pytest targets (`test`, `test-unit`, `test-integration`, `test-integration-parallel`) include this flag for consistent coverage visibility.

## Capabilities

This is a pure tooling/developer-experience change with no spec-level behavior changes. Coverage reporting format does not affect the system's capabilities, APIs, or behaviors — it only changes what the developer sees in the terminal.

`skip_specs: true` — no specs are needed.

## Impact

- **Files**: `Makefile` (update pytest invocations)
- **Dependencies**: No new dependencies — `pytest-cov` already supports `--cov-report term-missing`
- **Tests**: No test changes needed — this is a dev tooling change only