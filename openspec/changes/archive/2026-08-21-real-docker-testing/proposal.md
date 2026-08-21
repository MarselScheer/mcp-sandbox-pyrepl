## Why

The current test suite uses fakes (`FakeDockerClient`, `FakeSessionManager`) for unit tests that exercise Docker-dependent code. These fakes mask real integration issues — tests pass in CI but the MCP server fails when an agent actually uses it because the Docker integration path (`container_rpc` via `docker exec` + `logs()`, volume management, security constraints) is never exercised. We also have two diverging copies of `RealDockerClient` (src/ and tests/) that can drift silently.

## What Changes

- **Consolidate to one `RealDockerClient`**: Delete `tests/docker_adapter.py`, fix the `"logs": 1` discrepancy in `src/docker_adapter.py` (test copy has it, production copy doesn't)
- **Use testcontainers for Docker-dependent tests**: Replace manual Docker fixtures and fakes with `testcontainers`-managed containers that auto-cleanup
- **Tests that touch Docker use real Docker**: `test_session_manager.py`, `test_mcp_server.py`, `test_main.py` inject real `SessionManager` backed by testcontainers containers instead of fakes
- **Pure-domain tests stay unchanged**: `test_entrypoint_namespace.py`, `test_entrypoint_dispatcher.py`, `test_entrypoint_server.py`, `test_entrypoint_timeout.py`, `test_toolchain.py` remain as-is (no Docker dependency)
- **Add `testcontainers` dependency** to `pyproject.toml`
- **Import `RealDockerClient` from `src/docker_adapter`** in test code — single source of truth

## Capabilities

This is a testing infrastructure change with a minor production bug fix (the `"logs": 1` parameter in `attach_socket`). No spec-level behavior changes — the system's observable behavior, API contracts, and requirements remain the same. Spec skipping is declared in `.openspec.yaml` (`skip_specs: true`).

### New Capabilities

*(none — testing infrastructure only)*

### Modified Capabilities

*(none — no requirement changes)*

## Impact

- **Deleted file**: `tests/docker_adapter.py` (consolidated into `src/docker_adapter.py`)
- **Modified file**: `src/docker_adapter.py` (fix `attach_socket` params — add `"logs": 1`)
- **Modified file**: `tests/rpc_helpers.py` (import from `src.docker_adapter` instead of local)
- **Rewritten files**: `tests/conftest.py`, `tests/test_session_manager.py`, `tests/test_mcp_server.py`, `tests/test_main.py` (testcontainers fixtures, no fakes)
- **Added dependency**: `testcontainers>=4.0` to `pyproject.toml`
- **Build time**: Tests create real Docker containers — slower than fakes. Mitigation: session-scoped image + container reuse; parallel execution if needed later.
- **Docker requirement**: Tests that need Docker will skip gracefully if Docker is unavailable (preserving `docker_available`-style gating)