## Context

The project has ~80 well-written unit tests that use fakes (`FakeDockerClient`, `FakeSessionManager`) to validate each component in isolation. The architecture is cleanly layered:

```
MCP Server (mcp_server.py)
       │ DI: SessionManager
       ▼
SessionManager (session_manager.py)
       │ DI: DockerClient (Protocol)
       ▼
Docker SDK ──▶ Container ──▶ entrypoint.py (JSON-RPC)
```

The integration gap is at the Docker boundary. No test ever spins up a real container, executes code inside it, or validates the JSON-RPC communication protocol. The `DockerClient` Protocol adapter is the natural seam for unit testing, but we need tests that exercise the real adapter too.

## Goals / Non-Goals

**Goals:**
- Create a pytest-based integration test suite using real Docker containers
- Validate the full stack from `SessionManager` through Docker to the entrypoint JSON-RPC server
- Cover session lifecycle, code execution, package installation, file I/O, timeout enforcement, and session isolation
- Make integration tests self-skipping when Docker is unavailable
- Keep integration tests clean and readable, following the same behavior-driven patterns as existing unit tests

**Non-Goals:**
- Replacing or duplicating existing unit tests
- Testing Docker daemon availability or Docker SDK internals
- Testing MCP protocol transport (HTTP/SSE) — that's an end-to-end test concern, not an integration test
- CI pipeline configuration (that's a separate change)
- Performance or load testing

## Decisions

### Decision 1: Test at the SessionManager layer, not the MCP layer

Integration tests will exercise the `SessionManager` directly with a real `DockerClient` (the docker SDK adapter). This tests the critical integration boundary — host ↔ container communication via JSON-RPC — without the indirection of the MCP protocol layer.

**Alternatives considered:**
- **MCP layer testing**: Would test the full stack including MCP tool handlers. Rejected because the MCP layer is a thin pass-through with no additional logic beyond calling `SessionManager`. The MCP layer is already well-covered by unit tests with `FakeSessionManager`. Adding the MCP layer to integration tests would only add HTTP/SSE transport complexity without testing any additional logic.
- **Direct container exec**: Using `docker exec` to run code instead of the JSON-RPC entrypoint. Rejected because that bypasses the very protocol we need to validate.

### Decision 2: Use pytest markers and auto-skip for Docker availability

Integration tests use `@pytest.mark.integration` and a session-scoped fixture that checks for Docker availability. If Docker is unavailable, all integration tests are skipped with a clear message.

```python
@pytest.fixture(scope="session")
def docker_available() -> bool:
    try:
        docker.from_env().ping()
        return True
    except Exception:
        return False

@pytest.fixture(scope="session")
def docker_client(docker_available: bool):
    if not docker_available:
        pytest.skip("Docker daemon not available")
    return docker.from_env()
```

### Decision 3: Session-scoped image build, function-scoped containers

Building the sandbox Docker image is expensive (~30-60 seconds). The image fixture is session-scoped so it builds once per test run. Container fixtures are function-scoped so each test gets a clean session.

```
docker_client        session-scoped  (skip if Docker unavailable)
sandbox_image         session-scoped  (build once)
session_manager       function-scoped (new SessionManager per test)
session               function-scoped (new container, auto-cleanup)
```

### Decision 4: Test file organization mirrors existing structure

Instead of one monolithic integration test file, integration tests are organized by capability, mirroring the unit test structure:

| File | Covers |
|---|---|
| `tests/test_integration_session.py` | Session lifecycle (create, list, get, end) |
| `tests/test_integration_execution.py` | Code execution (expressions, state, errors, timeout, reset) |
| `tests/test_integration_packages.py` | Package installation and isolation |
| `tests/test_integration_files.py` | File I/O (write, read, list) |
| `tests/test_integration_security.py` | Security constraints (non-root, read-only rootfs, network isolation) |

### Decision 5: Use a conftest.py for shared fixtures

A single `tests/conftest.py` defines all shared fixtures. This keeps test files focused on test cases, not setup boilerplate. The conftest fixtures are the "arrange" phase of each integration test.

### Decision 6: Use a single default Python version for integration tests

Integration tests use a single Python version (the latest supported, e.g., 3.12) to keep image build time reasonable. Testing multiple Python versions is valuable but belongs in CI matrix configuration, not local test runs.

**Alternative considered:** Build and test against all configured Python versions. Rejected because it would add 3-5 minutes of image build time per test run, making local development impractical. Multi-version testing is better handled by CI matrix jobs.

### Decision 7: Cleanup is guaranteed via pytest fixture finalization

All container and data directory cleanup uses pytest fixture `yield` finalization, ensuring cleanup runs even on test failure. The `end_session` method is called in the teardown phase with idempotent semantics (already handled by the existing implementation).

## Risks / Trade-offs

- **Docker daemon required**: Tests require a running Docker daemon. Mitigation: auto-skip with clear message when unavailable. CI must provide Docker-in-Docker or Docker socket access.
- **Image build time**: First run takes ~30-60 seconds to build the sandbox image. Mitigation: session-scoped fixture builds once; subsequent test runs are fast if the image is cached. Document this in the README.
- **Test isolation**: Containers share the host Docker daemon and network. Mitigation: each test gets its own container with a unique session ID. No shared state between tests.
- **Orphaned containers on crash**: If the test process is killed, containers may not be cleaned up. Mitigation: fixture finalization handles normal teardown; for abnormal crashes, document `docker ps -a --filter "name=sess_" | xargs docker rm -f` as a cleanup command.

## Open Questions

- **CI integration**: Should integration tests run on every PR, or only on main? Decision deferred to the CI configuration change (out of scope for this change).
- **Data directory cleanup**: The current `end_session` implementation cleans up `/data` directories. Should integration tests also clean up `data/sess_*` on the host? The existing implementation handles this; tests just need to validate it works.
