## Why

When a caller provides Python code containing both `def` blocks and code that invokes them in a single `execute_python()` call, `compile()` with `'single'` mode fails ("multiple statements found while compiling a single statement"). The current fallback to `'exec'` mode causes display hook output for evaluated expressions to be silently lost. Callers are unaware of this restriction and get inconsistent results.

## What Changes

- **Document the restriction**: Improve docstrings on the `execute_python` MCP tool and the `Namespace.exec()` method to clearly state that multi-line `def`/`class` blocks must be defined in a separate call from the code that invokes them
- No code logic changes in `entrypoint.py` or `session_manager.py` — pure documentation improvement
- No API contract changes — signatures and response shapes remain exactly as today

## Capabilities

This is a pure documentation improvement with no spec-level behavioral changes. The system's observable behavior, API contracts, and requirements remain unchanged. Spec skipping is declared in `.openspec.yaml` (`skip_specs: true`).

### New Capabilities
*(none)*

### Modified Capabilities
*(none — no requirement changes)*

## Impact

- **`src/mcp_server.py`**: `MCPToolHandler.execute_python()` docstring updated with the restriction
- **`src/entrypoint.py`**: `Namespace.exec()` docstring updated with the restriction
- No test changes needed — existing behavior is preserved exactly