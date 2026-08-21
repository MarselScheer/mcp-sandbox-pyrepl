## Context

See proposal.md — Why and What Changes for motivation. The current test architecture has:

- **FakeDockerClient** in `test_session_manager.py` — returns canned responses, never touches Docker
- **FakeSessionManager** in `test_mcp_server.py` — same pattern for the MCP handler layer
- **FakeDockerClient** in `test_main.py` — same pattern for factory tests
- **Two copies of RealDockerClient** — `src/docker_adapter.py` (production) and `tests/docker_adapter.py` (test copy, already diverged on `attach_socket` params)
- **Integration tests** that already use real Docker, but with manual fixture management (no testcontainers)

The `DockerClient` Protocol in `session_manager.py` is the boundary. `SessionManager` receives a `DockerClient` via constructor injection. The production code uses `RealDockerClient` (which wraps `docker-py`). Tests will use the same `RealDockerClient` against real containers.

The sandbox image (`sandbox-base:3.12`) is prebuilt via `make build-image` — no image building during tests.

## Goals / Non-Goals

**Goals:**
- Every test that exercises Docker-dependent code does so against a real Docker container
- Single version of `RealDockerClient` (in `src/`, imported from `tests/`)
- Auto-cleanup of containers on test exit (even on exceptions)
- Graceful skip when Docker is unavailable
- All existing tests preserved (same scenarios, same assertions)
- `make build-image` target to build the sandbox image

**Non-Goals:**
- Parallel test execution (deferred — can be added later if slow)
- Changing the pure-domain tests (`test_entrypoint_*.py`, `test_toolchain.py`)
- Changing the production code architecture (DI, Protocols, etc. stay as-is)
- Changing the `SessionManager` API or `DockerClient` Protocol
- Image building during tests (assumes prebuilt image)
- Merging integration test files into unit test files (they stay separate)

## Decisions

### 1. Use `testcontainers` `DockerContainer` for container management

**Decision**: Use `testcontainers`'s `DockerContainer` for the sandbox container.

**Rationale**: 
- `DockerContainer` is the standard testcontainers Python container type
- Provides `start()`, `stop()`, `with_env()`, `with_user()`, `with_read_only()`, `with_volume_mapping()`, `with_tmpfs()` — maps directly to the Docker options we need
- `wait_for_logs()` for readiness checks (instead of `time.sleep(0.3)` in the production code)
- Auto-cleanup via `stop()` in fixture teardown — no orphan containers
- No image building needed — we just reference the prebuilt `sandbox-base:3.12` tag

**Alternatives considered**:
- Manual `docker-py` fixtures (current approach) — no auto-cleanup, no readiness checks, verbose
- `pytest-docker-tools` — less maintained, smaller ecosystem
- Raw `docker-py` with `pytest.fixture` for cleanup — works but testcontainers adds readiness checks and cleanup guarantees

### 2. No image building in tests — prebuilt via `make build-image`

**Decision**: Tests assume `sandbox-base:3.12` is already present in the Docker daemon. The `Makefile` gets a `build-image` target.

```makefile
build-image:
	uv run docker build \
		-t sandbox-base:3.12 \
		-f images/sandbox-base/Dockerfile \
		--build-arg PYTHON_VERSION=3.12 \
		.
```

**Rationale**: The image is built once (via `make build-image` or CI pipeline) before tests run. Building it during tests adds 30-60s per test run, wasted time since the image rarely changes. If the image is missing, `DockerContainer` will fail to start with a clear `ImageNotFound` error — which is the correct behavior.

### 3. Fixture architecture: two-layer

```python
# conftest.py

# Layer 1: Docker connectivity (session-scoped, optional)
@pytest.fixture(scope="session")
def docker_available() -> bool:
    """Check if Docker daemon is available and the image exists."""
    try:
        import docker
        client = docker.from_env()
        client.ping()
        client.images.get("sandbox-base:3.12")
        return True
    except Exception:
        return False

# Layer 2: SessionManager (function-scoped — each test gets clean state)
@pytest.fixture
def session_manager(docker_available: bool) -> SessionManager:
    if not docker_available:
        pytest.skip("Docker or sandbox-base:3.12 image not available")

    import docker
    from docker_adapter import RealDockerClient
    from session_manager import SessionManager, SessionManagerConfig

    client = docker.from_env()
    adapter = RealDockerClient(client)
    config = SessionManagerConfig(
        image_registry={"3.12": "sandbox-base:3.12"},
        default_python_version="3.12",
        network_name="bridge",
        container_user="1000",
    )
    return SessionManager(docker=adapter, config=config)
```

**Rationale**: 
- Session-scoped for Docker connectivity check (cheap, one-time)
- Function-scoped for `SessionManager` — each test gets a fresh container, no cross-test state pollution
- Image existence check is part of `docker_available` — fail fast if image is missing

### 4. Marker strategy: integration tests stay separate

**Decision**: Keep the `@pytest.mark.integration` marker on integration test files. The unit tests that were previously faked now use real Docker via the `session_manager` fixture, but they are NOT marked as integration tests. The `test_integration_*.py` files remain separate with their marker.

**Rationale**: 
- `test_session_manager.py`, `test_mcp_server.py`, `test_main.py` test the component's behavior, not the full stack — they just happen to use real Docker for truthfulness
- `test_integration_*.py` test cross-cutting concerns (security, packages, files, session isolation) that span multiple components
- The `-m "not integration"` exclusion in `addopts` continues to work, but now only excludes the explicitly integration-focused tests, not all Docker tests

### 5. `RealDockerClient` consolidation

**Decision**: 
1. Fix `src/docker_adapter.py` `attach_socket` params to include `"logs": 1` (the test copy had it, production didn't — likely a bug)
2. Delete `tests/docker_adapter.py`
3. Update `tests/rpc_helpers.py` to import from `src.docker_adapter`
4. The `pythonpath = ["src"]` in `pyproject.toml` already makes `from docker_adapter import RealDockerClient` resolve to `src/`

**Rationale**: Single source of truth. The divergent `"logs": 1` param was a real bug — the production `attach_socket` wasn't attaching to the log stream, which could affect `container_rpc` behavior.

### 6. Test file structure after migration

| File | Docker? | After |
|---|---|---|
| `test_entrypoint_namespace.py` | No | Unchanged |
| `test_entrypoint_dispatcher.py` | No | Unchanged |
| `test_entrypoint_server.py` | No | Unchanged |
| `test_entrypoint_timeout.py` | No | Unchanged |
| `test_toolchain.py` | No | Unchanged |
| `test_session_manager.py` | Yes | Rewritten — uses real `SessionManager` via `session_manager` fixture, no fakes |
| `test_mcp_server.py` | Yes | Rewritten — uses real `SessionManager` via `session_manager` fixture, no fakes |
| `test_main.py` | Yes | Rewritten — factory tests use real Docker, no fakes |
| `test_integration_session.py` | Yes | Unchanged — uses shared `session_manager` fixture, keeps `@pytest.mark.integration` |
| `test_integration_execution.py` | Yes | Unchanged — uses shared `session_manager` fixture, keeps marker |
| `test_integration_files.py` | Yes | Unchanged — uses shared `session_manager` fixture, keeps marker |
| `test_integration_packages.py` | Yes | Unchanged — uses shared `session_manager` fixture, keeps marker |
| `test_integration_security.py` | Yes | Unchanged — uses shared `session_manager` fixture, keeps marker |

## Risks / Trade-offs

- **[Speed]** Each Docker-dependent test creates and destroys a real container. A typical test suite run will be slower than current fakes.
  → **Mitigation**: No image building in tests. Container creation is O(seconds). If too slow, add parallel execution (`pytest-xdist`).
- **[CI]** Docker must be available in CI.
  → **Mitigation**: Tests skip gracefully when Docker is unavailable. CI already has Docker (it's needed for the MCP server to work).
- **[Container leaks]** If a test crashes hard, the container might not be cleaned up.
  → **Mitigation**: testcontainers has built-in cleanup via `ryuk` (a sidecar container that monitors and cleans up orphan containers). Also, `pytest.fixture` finalization runs even on exceptions.
- **[Port conflicts]** No port binding needed — `SessionManager` communicates via `docker exec` + `logs()`, not TCP. No port conflicts.
- **[Missing image]** If `sandbox-base:3.12` isn't prebuilt, tests fail with `ImageNotFound`.
  → **Mitigation**: The `docker_available` fixture checks for the image and skips tests with a clear message. `make build-image` builds it first.