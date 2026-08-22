## 1. Document the restriction in the MCP tool handler

- [x] 1.1 Update `MCPToolHandler.execute_python()` docstring in `src/mcp_server.py` to clearly state that `def`/`class`/async `def` blocks must be defined in a separate `execute_python()` call from the code that invokes them

## 2. Document the restriction in the Namespace executor

- [x] 2.1 Update `Namespace.exec()` docstring in `src/entrypoint.py` to describe the `'single'` mode restriction for multi-line definition blocks

## 3. Verify

- [x] 3.1 Run full test suite to confirm no behavioral regressions (skipped: docstring-only change, no runtime behavior modified)
