## Why

The project has ~80 well-written behavior-driven unit tests, but zero integration tests that exercise the full stack against real Docker containers. Every test uses fakes (`FakeDockerClient`, `FakeSessionManager`). While the unit tests validate individual components in isolation, they cannot detect regressions in the Docker SDK interaction, container entrypoint behavior, JSON-RPC communication over stdin/stdout, timeout enforcement in real containers, package installation with real `uv pip install`, or filesystem I/O on real Docker volumes. Adding integration tests closes this gap and provides confidence that the system works end-to-end.

## What Changes

- Add a pytest-based integration test suite with real Docker container lifecycle management
- Add a `conftest.py` with session-scoped fixtures for building sandbox images and managing container setup/teardown
- Add a `pytest.mark.integration` marker to separate integration tests from unit tests (integration tests require Docker and are slower)
- Add integration tests for the full stack: create a session via `SessionManager`, execute code via JSON-RPC to the running container, and validate results
- Add integration tests for package installation, file I/O, timeout enforcement, session lifecycle, and multi-session isolation
- Update `pyproject.toml` with the new marker and optional test configuration
- Add a Makefile target for running integration tests

## Capabilities

### New Capabilities
- `integration-tests`: End-to-end test suite that validates the full stack (MCP tools → SessionManager → Docker containers → entrypoint JSON-RPC server) against real Docker containers. Covers session lifecycle, code execution, package installation, file I/O, timeout enforcement, and session isolation.

### Modified Capabilities
<!-- No existing specs are changing their requirements. Integration tests validate existing behavior. -->

## Impact

- **New files**: `tests/conftest.py`, `tests/test_integration_*.py` (likely 4-5 test modules)
- **Modified files**: `pyproject.toml` (pytest markers), `Makefile` (integration test target)
- **Dependencies**: Requires a running Docker daemon; no new Python packages needed (docker SDK already in dependencies)
- **CI/CD**: Integration tests should be runnable in CI but likely as a separate job/pipeline stage since they require Docker-in-Docker or a Docker socket
