## 1. Project Setup

- [ ] 1.1 Add `integration` marker to `pyproject.toml` under `[tool.pytest.ini_options]`, add `-m "not integration"` as default to exclude integration tests from `pytest`
- [ ] 1.2 Add `test-integration` target to `Makefile` that runs `pytest -m integration` with optional args

## 2. Shared Fixtures (conftest.py)

- [ ] 2.1 Create `tests/conftest.py` with a `docker_available` session-scoped fixture that checks Docker daemon availability and skips if unavailable
- [ ] 2.2 Add `docker_client` session-scoped fixture that returns `docker.from_env()` (skips with `pytest.skip` if Docker unavailable)
- [ ] 2.3 Add `sandbox_image` session-scoped fixture that builds the `sandbox-base:3.12` Docker image via `docker.images.build()` (or pulls from cache), pointing at `images/sandbox-base/`
- [ ] 2.4 Add `session_manager` function-scoped fixture that creates a `SessionManager` with the real Docker client and a config pointing to the built image
- [ ] 2.5 Add `session` function-scoped fixture that creates a session via `session_manager.create_session()` and yields the session ID, then calls `end_session()` in teardown
- [ ] 2.6 Add `data_dir` fixture that resolves the host-side data directory path for a given session, enabling host-side file I/O validation

## 3. Session Lifecycle Integration Tests

- [ ] 3.1 Create `tests/test_integration_session.py` with test for creating a session with default Python version, verifying the container starts and returns a session ID
- [ ] 3.2 Add test for listing active sessions (create a session, verify it appears in `list_sessions()`)
- [ ] 3.3 Add test for getting session info via `get_session()` (verify metadata presence)
- [ ] 3.4 Add test for ending a session (container stops, session removed from active list)
- [ ] 3.5 Add test for idempotent end_session (end twice, both succeed)
- [ ] 3.6 Add test for creating a session with a custom image reference

## 4. Code Execution Integration Tests

- [ ] 4.1 Create `tests/test_integration_execution.py` with test for executing code and capturing stdout output
- [ ] 4.2 Add test for display hook capture (expression that produces a value)
- [ ] 4.3 Add test for state persistence across multiple `execute_python` calls
- [ ] 4.4 Add test for syntax error reporting
- [ ] 4.5 Add test for runtime error reporting with traceback
- [ ] 4.6 Add test for execution timeout enforcement (sleep longer than timeout)
- [ ] 4.7 Add test for namespace reset clearing session state

## 5. Package Installation Integration Tests

- [ ] 5.1 Create `tests/test_integration_packages.py` with test for installing a package and using it in subsequent code execution
- [ ] 5.2 Add test for package isolation between two independent sessions (package installed in session A unavailable in session B)

## 6. File I/O Integration Tests

- [ ] 6.1 Create `tests/test_integration_files.py` with test for host writing a file to the data volume and the container reading it via `open()`
- [ ] 6.2 Add test for container writing a file to `/data/` and the host reading it back from the data directory

## 7. Security Constraint Integration Tests

- [ ] 7.1 Create `tests/test_integration_security.py` with test verifying the container runs as non-root user (UID 1000)
- [ ] 7.2 Add test verifying that writing outside `/data/` (e.g., `/tmp/test.txt`) fails with permission error
- [ ] 7.3 Add test verifying network isolation during code execution (outbound HTTP fails)
- [ ] 7.4 Add test verifying session isolation between two independent sessions (separate namespaces, ending one doesn't affect the other)

## 8. Validation

- [ ] 8.1 Run `pytest -m integration -v --tb=short` and verify all integration tests pass (or skip gracefully if Docker unavailable)
- [ ] 8.2 Run `pytest -v --tb=short` and verify existing unit tests still pass (integration tests excluded by default marker)
- [ ] 8.3 Run `make test-integration` and verify the Makefile target works
