## 1. Infrastructure Setup

- [x] 1.1 Add `testcontainers>=4.0` to `[dependency-groups] dev` in `pyproject.toml`
- [x] 1.2 Add `build-image` target to `Makefile` for building `sandbox-base:3.12`
- [x] 1.3 Update `[tool.pytest.ini_options]` in `pyproject.toml` — remove `-m "not integration"` from `addopts` (tests skip themselves via fixture), keep the `integration` marker for integration test files

## 2. Consolidate RealDockerClient

- [x] 2.1 Fix `src/docker_adapter.py`: add `"logs": 1` to `attach_socket` params (the test copy had it, production didn't)
- [x] 2.2 Delete `tests/docker_adapter.py` (duplicate — single source of truth is `src/docker_adapter.py`)
- [x] 2.3 Update `tests/rpc_helpers.py` to import `RealDockerClient` from `src.docker_adapter` (already works via `pythonpath = ["src"]`)

## 3. Rewrite conftest.py with Testcontainers Fixtures

- [x] 3.1 Replace manual Docker fixtures with testcontainers-based fixtures
- [x] 3.2 Add `docker_available` session-scoped fixture (checks Docker daemon + image existence)
- [x] 3.3 Add `session_manager` function-scoped fixture (creates real `SessionManager` with `RealDockerClient` backing)
- [x] 3.4 Remove `sandbox_image` build fixture (image is prebuilt, no building in tests)
- [x] 3.5 Keep `exec_in_container` helper (useful for integration tests)

## 4. Rewrite test_session_manager.py (No Fakes)

- [x] 4.1 Remove `FakeDockerClient`, `FakeContainer`, `DockerPyStyleClient` classes
- [x] 4.2 Remove `_container_id` helper (use `session_manager.get_session()` directly)
- [x] 4.3 Rewrite `TestSessionManagerCreate` — inject `session_manager` fixture, keep all test scenarios
- [x] 4.4 Rewrite `TestSessionManagerEnd` — same scenarios, real container
- [x] 4.5 Rewrite `TestSessionManagerList` — same scenarios, real container
- [x] 4.6 Rewrite `TestSessionManagerNetwork` — same scenarios, real container
- [x] 4.7 Rewrite `TestSessionManagerExec` — same scenarios, real container
- [x] 4.8 Remove `test_create_session_fails_with_dockerpy_style_client` (no longer relevant — only tests that the adapter wraps correctly)
- [x] 4.9 Remove `test_send_exec_returns_stdout/error/display` (these were testing the fake's canned response, not real behavior — the real `send_exec` behavior is tested in integration tests)

## 5. Rewrite test_mcp_server.py (No Fakes)

- [x] 5.1 Remove `FakeSessionManager` class
- [x] 5.2 Rewrite tests to inject `session_manager` fixture into `MCPToolHandler`
- [x] 5.3 Keep all test scenarios but against real containers
- [x] 5.4 Tests that verify call shape (e.g., `test_execute_code_in_session` checks `len(sm.exec_calls)`) become behavior tests (e.g., `result["stdout"]` is empty string for real exec)

## 6. Rewrite test_main.py (No Fakes)

- [x] 6.1 Remove `FakeDockerClient` class
- [x] 6.2 Rewrite `TestCreateSessionManager` — inject real Docker client through `create_session_manager`
- [x] 6.3 Rewrite `TestCreateMCPApp` — inject real Docker client through `create_mcp_app`
- [x] 6.4 Keep `TestLoadConfig` and `TestSetupSignalHandlers` unchanged (no Docker dependency)

## 7. Update Integration Tests

- [x] 7.1 Update `test_integration_*.py` files to import `session_manager` fixture from `conftest.py` (they already do — verify they still work)
- [x] 7.2 Remove `docker_client` and `sandbox_image` fixture references from integration tests (these are now in `conftest.py`)
- [x] 7.3 Verify `@pytest.mark.integration` markers are still in place

## 8. Verify

- [x] 8.1 Run `make build-image` to build the sandbox image
- [x] 8.2 Run `uv run pytest tests/ -v --tb=short` — all Docker-dependent tests pass against real containers
- [x] 8.3 Run `uv run pytest tests/ -v --tb=short -m integration` — integration tests still work
- [x] 8.4 Run `uv run pytest tests/ -v --tb=short` without Docker — Docker-dependent tests skip gracefully, pure-domain tests pass
- [x] 8.5 Run `uv run ruff check src/ tests/` — no lint issues
- [x] 8.6 Verify `tests/docker_adapter.py` is deleted and no imports reference it