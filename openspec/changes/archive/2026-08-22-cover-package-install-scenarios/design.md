## Context

See proposal.md — the package management spec defines 7 scenarios; 5 are tested via direct Docker commands, 2 are untested (version-specific and multi-package install), and the MCP tool-level tests (`TestInstallPackages` in `test_mcp_server.py`) only verify response format, never actual importability.

Existing tests bypass the tool contract entirely — they call `container.exec_run` directly rather than `MCPToolHandler.install_packages`. The conftest provides a `session_manager` fixture backed by real Docker containers, and `class_container` for container-scoped tests.

## Goals / Non-Goals

**Goals:**
- All 7 package management spec scenarios tested at the MCP tool handler level with real Docker containers
- Tests go through `MCPToolHandler.install_packages` (the public API), not direct `docker.exec_run`
- New tests cover: version-specific install, multi-package install, network isolation after install (network removal blocks subsequent network calls)
- Existing `test_packages.py` integration tests converted to use the MCP tool handler interface where feasible
- Tests are isolated from each other (each creates its own session via `session_manager` fixture)

**Non-Goals:**
- No changes to the MCPToolHandler, SessionManager, or PackageInstaller implementation (unless a test reveals a bug)
- No unit tests for the entrypoint dispatcher's install method (already covered by `test_entrypoint_dispatcher.py`)
- No changes to the spec itself (all scenarios are already specified)

## Decisions

1. **Write new tests in `test_mcp_server.py` rather than `test_packages.py`**
   - **Rationale**: The MCP tool handler is the public API boundary — tests should exercise it. `test_packages.py` tests bypass the handler. The new tests belong alongside existing `TestInstallPackages` class.
   - **Alternative considered**: Adding to `test_packages.py` — rejected because it would keep testing the wrong abstraction layer (direct Docker commands).

2. **Each test creates its own session via `session_manager` fixture**
   - **Rationale**: The existing `TestInstallPackages` pattern already does this. Session creation is fast (container is reused from the pool). Isolation between tests is automatic.
   - **Alternative considered**: Reusing a class-scoped container (like `test_packages.py`'s `class_container`) — rejected because the MCP tests already use per-test sessions and that pattern keeps tests independent.

3. **Verify importability via `execute_python` after install**
   - **Rationale**: The spec says "the package is importable in subsequent `execute_python` calls". The existing MCP tests only check the install response format. Adding `execute_python` assertions closes that gap.
   - **Alternative considered**: Using `container.exec_run` to verify — rejected because it tests Docker commands, not the tool contract.

4. **Use packages with fast installs (six, pytz) for quick tests**
   - **Rationale**: Some spec scenarios reference `pandas` (slow to download). For the network isolation test and version-specific test, small packages are preferred to keep test runtimes down.
   - Version-specific test: a small package like `markupsafe==2.1.0` or `six==1.16.0` — avoid `pandas==2.0.0` which is large.

5. **Network isolation: run `execute_python` with a network call (requests/urllib) and expect failure**
   - **Rationale**: The spec requires "any subsequent `execute_python` code that attempts network access SHALL fail". The test installs a package requiring network, then calls `execute_python` with a `urllib.request` call and asserts it fails.
   - **Risks**: If the container has no `urllib` failure mode (e.g., it hangs instead of erroring), we may need a timeout or alternative assertion approach.

## Risks / Trade-offs

- **[Risk] Install may be slow**: Multiple package installations (numpy, scipy) can take minutes. Mitigation: use small packages (`six`, `pytz`, `markupsafe`) for the version-specific and network tests. Use `numpy` only where the spec explicitly requires it.
- **[Risk] Test flakiness**: Network-dependent tests (install) can fail if Docker network is slow or flaky in CI. Mitigation: the existing `docker_available` fixture handles graceful skip when Docker is unavailable.
- **[Risk] Package version availability**: Hardcoded versions (`markupsafe==2.1.0`) may become unavailable in the future. Mitigation: acceptable trade-off; update test data on failure.
- **[Trade-off] Not converting `test_packages.py` full suite**: The isolation test in `test_packages.py` uses two separate containers (two sessions). Converting it to use `MCPToolHandler` would be unnatural since it tests Docker-level isolation. Keep it as-is for that specific scenario.