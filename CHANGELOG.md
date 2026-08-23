# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] — 2026-08-23

### Added

- **Optimized speed test workflow** — New `test-optimized-speed` Makefile target running unit tests first (fast, no Docker), then integration tests in parallel (`test-unit && test-integration-parallel`)
- **Comprehensive check workflow** — New `check-all` Makefile target running `format → format-check → lint → typecheck → test-optimized-speed`, replacing the old `check` target, providing a single-command pre-commit/CI gate
- **Named volume cleanup on container removal** — `RealDockerClient.container_remove()` now inspects container mounts before removal, collects named volume names (`Type == "volume"`), removes the container, then removes each volume. Volume removal failures are silently suppressed (e.g. in-use volumes on parallel test runs)
- **`_create_container()` helper** (`session_manager.py`) — Extracted common container creation parameters (named volumes, tmpfs, read-only root, etc.) into a private method shared by `create_session()` and `restart_session()`, eliminating duplicated volume configuration
- **`_merge_config()` function** (`main.py`) — Extracted config merging logic from `load_config()` into a testable pure function
- **`_default_shutdown_handler()` function** (`main.py`) — Extracted default signal handler to module level so it can be used as a real default parameter (no `None` sentinel)
- **Unit tests for error handling paths** (`tests/unit/test_session_manager.py`, `tests/unit/test_mcp_server.py`) — Fast, Docker-free tests covering session corruption recovery, package install exception handling, network operations on nonexistent sessions, and file operations on nonexistent sessions
- **`stub_dispatcher` fixture** (`tests/unit/conftest.py`) — Shared fixture wiring `RPCDispatcher` with no-op fakes (`Namespace`, `NoOpTimeoutStrategy`, `FakePackageInstaller`) for routing-only server loop tests
- **`FakePackageInstaller` shared fixture** — Moved from inline class in `test_entrypoint_dispatcher.py` to shared `tests/unit/conftest.py` for reuse across unit test files
- **`dummy_image_registry` fixture** (`tests/integration/conftest.py`, `tests/unit/conftest.py`) — Minimal image registry fixture for tests that don't exercise version listing
- **Config merging tests** (`TestMergeConfig` in `tests/unit/test_main.py`) — Tests verifying user config merges correctly into defaults for images, defaults, and data_dir overrides
- **Config loading error handling tests** (`TestLoadConfigErrors` in `tests/unit/test_main.py`) — Tests verifying malformed YAML falls back to default configuration
- **Volume cleanup integration tests** (`tests/integration/test_session.py`) — `test_end_session_removes_named_volumes` verifying named Docker volumes are removed after session end, and `test_session_fixture_teardown_cleans_up_containers_and_volumes` verifying fixture teardown handles cleanup without explicit `end_session()` call

### Changed

- **Dependency injection: `None` sentinel elimination** — All `Optional[T] = None` patterns with hidden fallback creation replaced with required parameters or real defaults across the codebase:
  - `RPCDispatcher.__init__()` — `namespace`, `timeout_strategy`, `installer`, and `config` are now **required** parameters (no fallback creation)
  - `SessionServer.__init__()` — `dispatcher` is now **required**; `stdin`/`stdout` default to `sys.stdin`/`sys.stdout` (real, usable values)
  - `MCPToolHandler.__init__()` — `image_registry` is now **required** (no hidden built-in default registry)
  - `SessionManager.__init__()` — `config` defaults to `SessionManagerConfig()` (frozen dataclass — safe immutable default, not a sentinel)
  - `create_session_manager()` / `create_mcp_app()` (`main.py`) — `docker_client` is now **required** (caller must provide it explicitly)
  - `load_config()` (`main.py`) — `config_path` is now **required**; caller calls `sanitize_config_path()` before passing it
  - `setup_signal_handlers()` (`main.py`) — `signal_handler` defaults to `_default_shutdown_handler` (callable, real default); `register` defaults to `signal.signal` (callable, real default)
  - `entrypoint.py:main()` — Explicitly constructs all dependencies (`RPCDispatcherConfig`, `Namespace`, `ThreadTimeoutStrategy`, `PackageInstaller`, `RPCDispatcher`, `SessionServer`) instead of relying on `None` fallback defaults
- **`main.py` startup flow** — Docker client is now created early (before MCP app creation), failing fast with a clear error if Docker is unavailable. The created client is then passed explicitly to `create_mcp_app()` and `create_session_manager()`, making the dependency chain fully visible in the composition root
- **`MCPToolHandler.create_session()`** — `python_version` is now optional (`None` means use the `SessionManager`'s configured default). When both `python_version` and `image` are `None`, neither is passed to `SessionManager.create_session()` (previously always passed `python_version="3.12"`)
- **`RealDockerClient.containers_create()`** — Removed unused `command` and `name` parameters from the method and the `DockerClient` Protocol
- **Fixture teardown** (`tests/integration/conftest.py`) — `session_manager` fixture converted to generator-yield pattern with teardown that ends remaining sessions and removes the data directory. `class_container` fixture now also cleans up the data directory on teardown
- **Integration tests using `MCPToolHandler`** — All now pass `dummy_image_registry` explicitly instead of relying on `MCPToolHandler`'s built-in default
- **Unit test routing tests** (`test_entrypoint_dispatcher.py`, `test_entrypoint_server.py`) — Migrated from inline `FakePackageInstaller` and inline dispatcher construction to the shared `stub_dispatcher` fixture where applicable, and explicitly construct dispatchers with all required dependencies otherwise
- **Makefile** — Replaced `check` target with `check-all` which runs the complete `format → format-check → lint → typecheck → test-optimized-speed` pipeline
- **README** — Updated Makefile targets documentation with `test-optimized-speed` and `check-all`

### Fixed

- **Named Docker volume leak** — `RealDockerClient.container_remove()` now inspects and removes auto-generated named volumes (`vol_<uuid>`) after removing the container, preventing orphaned volumes from accumulating on the Docker host
- **Test session leaks** — `tests/integration/test_main.py` and `tests/integration/test_session_manager.py` now use `try/finally` to ensure sessions are ended even on assertion failure, preventing container and volume leaks from failed tests
- **Fixture resource leaks** — `session_manager` fixture in `tests/integration/conftest.py` now properly tears down remaining sessions and removes the temp `data_dir` via generator-yield pattern; `class_container` fixture now also cleans up `data_dir` on teardown

### Documentation

- **Design principles** (`.opencode/rules/design-principles.md`) — Added comprehensive "No `None` sentinels for dependencies" rule (section 2), detailing:
  - Why `None` sentinels with hidden fallback creation are an anti-pattern
  - Immutable defaults (`sys.stdin`, frozen dataclasses, callables) as safe alternatives
  - Mutable/stateful service objects as required parameters
  - Docstring hints for required params
  - Rule of thumb table for default type verdicts
  - The exception: `None` meaning "no value" (not "create something")
- **Anti-patterns table** — Added "`None` sentinel defaults" and "Duplicated defaults across layers" entries
- **README** — Updated Makefile targets documentation to include `test-optimized-speed` and `check-all`

## [0.4.2] — 2026-08-22

### Added

- **OpenSpec fast-forward workflow** — New `opsx-ff` command (`.opencode/commands/opsx-ff.md`) and `openspec-ff-change` skill (`.opencode/skills/openspec-ff-change/SKILL.md`) for quickly creating all OpenSpec artifacts needed for implementation without stepping through each one individually

### Changed

- **Coverage report output** — Makefile now outputs non-covered lines after test runs for easier identification of untested code

### Documentation

- **`execute_python()` MCP tool docstring** (`src/mcp_server.py`) — Added detailed documentation explaining the multi-line definition blocks restriction in `"single"` compile mode, with correct and incorrect usage examples showing when REPL display hook output is silently lost
- **`Namespace.execute()` docstring** (`src/entrypoint.py`) — Added documentation about the `"single"` vs `"exec"` compile mode fallback behavior, explaining why callers must split multi-line definition blocks from their invocation into separate calls

## [0.4.1] — 2026-08-22

### Fixed

- **`RealDockerClient.container_rpc()` request/response mismatching** — Added unique `request_id` (via `_rpc_counter`) to each JSON-RPC call so that responses are correctly matched when multiple calls accumulate in the container's log stream. Previously, a response from one call could be consumed by the wrong caller, causing hangs or stale data. This specifically affected the `install_packages` tool when sessions had an existing log backlog.

### Added

- **`test_version_specific_install`** (`tests/integration/test_mcp_server.py`) — Integration test exercising package installation with an explicit version constraint (`markupsafe==2.1.0`), verifying the installed version matches the request
- **`test_multi_package_install`** (`tests/integration/test_mcp_server.py`) — Integration test installing multiple packages in a single `install_packages` call (`six` and `pytz`), verifying all are importable afterward

### Changed

- **Package install integration tests through `MCPToolHandler`** — `tests/integration/test_packages.py` now routes all install/verify operations through `MCPToolHandler` instead of direct `docker exec` calls via the Docker SDK, testing the full MCP tool layer end-to-end
- **Network isolation verification** — `test_install_single_package` (now `test_install_packages_connects_and_disconnects_network`) additionally verifies that network is actually disconnected after package installation, by attempting a socket connection to `example.com` and asserting a network error

## [0.4.0] — 2026-08-22

### Added

- **`test-integration-parallel` Makefile target** — Runs integration tests in parallel via `pytest -n auto` (pytest-xdist), with UUID-scoped container names to avoid collisions. Expected runtime: ~35s on a 12-core machine (down from 5m25s baseline)
- **`test-unit` Makefile target** — Dedicated target for fast unit tests (no Docker needed), designed for the TDD cycle
- **`class_container` fixture** (`tests/integration/conftest.py`) — Class-scoped fixture that creates one container per test class instead of per test, eliminating per-test container startup overhead for tests that don't require session isolation
- **`pytest-xdist` dependency** — Added to dev dependency group for parallel test execution support
- **Timing instrumentation** — `time.perf_counter()` hooks in `session_manager` and `session` fixtures, plus per-RPC timing logs in `container_rpc()`, enabling per-phase runtime attribution for performance profiling

### Changed

- **Test directory restructured** — Tests split into `tests/unit/` and `tests/integration/` subdirectories for clear separation:
  - Unit tests moved to `tests/unit/` (fast, no Docker needed)
  - Integration tests moved to `tests/integration/` (require real Docker daemon)
  - `conftest.py` moved to `tests/integration/conftest.py` (integration-only fixtures)
  - `rpc_helpers.py` moved to `tests/integration/rpc_helpers.py`
  - `pytest testpaths` updated to `["tests/unit", "tests/integration"]`
- **`container_rpc()` polling mechanism** — Replaced `time.sleep(0.3)` fixed sleep with short-poll + exponential backoff (10ms initial, 100ms max, 10s total timeout). When the response is already present, the first iteration reads it within ~10ms — a 30x improvement over 300ms
- **Integration test serial target** — `test-integration` now uses `--durations=0` to show per-test timing breakdown. Expected runtime: ~3m40s (down from ~5m25s baseline)
- **Network isolation test** — Replaced `urllib.request.urlopen(timeout=5)` with `socket.socket()` and 0.5s timeout, detecting network disconnection in under 1 second instead of waiting for OS-level TCP timeout
- **Execution timeout test** — Replaced `timeout 5` CLI wrapper with the entrypoint's own JSON-RPC timeout mechanism (`timeout=1.0`), exercising the production `ThreadTimeoutStrategy` path instead of an OS-level timeout
- **`RealDockerClient` method signatures** — Reflowed multi-line signatures to single-line for consistency

### Removed

- **Integration test marker** — Removed the `integration` pytest marker and all related filtering from `pyproject.toml` and test files; all Docker tests now run by default

## [0.3.0] — 2026-08-21

### Added

- **`mise.toml`** — New project tool version manager configuration via `mise` for `node`, `uv`, and `@fission-ai/openspec`
- **`testcontainers` dependency** — Added `testcontainers >= 4.14.2` as a dev dependency for Docker container management during tests
- **Error handling in `install_packages` MCP tool** — Added `except Exception` handler in `MCPToolHandler.install_packages()` to return structured error results instead of crashing

### Changed

- **Real Docker containers in all tests** — All Docker-dependent tests now use real Docker containers instead of `FakeDockerClient`/`FakeSessionManager` fakes:
  - `test_session_manager.py` rewritten to use real containers via shared `session_manager` fixture
  - `test_mcp_server.py` rewritten to use real containers via shared `session_manager` fixture
  - `test_main.py` rewritten — factory tests use real Docker, no fakes
  - Single version of `RealDockerClient` imported from `src/docker_adapter.py` (test copy deleted)
  - `conftest.py` — Two-layer fixture architecture: session-scoped Docker availability check, function-scoped `SessionManager` with fresh containers
  - Integration tests (`test_integration_*.py`) now share the same `session_manager` fixture
  - `pytest addopts` — Removed `-m "not integration"` exclusion, all Docker tests run by default
- **`RealDockerClient.attach_socket` fix** — Added `"logs": 1` to `attach_socket` params for proper log stream attachment
- **`RealDockerClient.network_connect` idempotency** — Added no-op guard when container is already connected to the target network (avoids Docker 403 error)

### Upgraded

- **OpenSpec 1.8.0 → 1.9.0** — Upgraded the OpenSpec CLI (`@fission-ai/openspec`) and all associated commands and skills to version 1.9.0

## [0.2.1] — 2026-08-08

### Added

- **`ripgrep` in IDE Docker image** — Added `ripgrep` package to `docker-ide/Dockerfile` for fast codebase search
- **`/opsx-verify` command** — New OpenSpec command (`opsx-verify`) that verifies implementation matches change artifacts (specs, tasks, design) before archiving
- **`openspec-verify-change` skill** — New skill for verifying that implementation is complete, correct, and coherent before archiving, with support for OpenSpec store integration
- **"Named Arguments at Call Sites" design principle** — New section 9 in `.eca/rules/design-principles.md` providing guidance on when to use keyword vs positional arguments, including heuristics, examples of good/bad patterns, and rules for booleans, numeric values, and injected dependencies

### Upgraded

- **OpenSpec 1.4.1 → 1.8.0** — Upgraded the OpenSpec CLI (`@fission-ai/openspec`) and all associated commands and skills (`opsx-*`, `openspec-*`) in `.eca/` to version 1.8.0, including new `opsx-update` and `openspec-update-change` commands

## [0.2.0] — 2026-08-06

### Added

- **Real Docker Client Adapter** (`RealDockerClient`) — Wraps the docker-py SDK to satisfy the `DockerClient` Protocol, enabling production use of real Docker containers:
  - Container lifecycle: create, start, get, stop, remove
  - JSON-RPC communication via docker exec to `/proc/1/fd/0` (entrypoint's stdin)
  - Network connect/disconnect for package installation isolation
  - Volume creation with auto-generated named volumes
  - `container_rpc()` for bidirectional stdin/stdout communication with the entrypoint

- **Integration Test Suite** — 5 test files (180+ tests) exercising the full Docker stack:
  - `test_integration_session.py` — Session lifecycle: create, list, get, end, restart, cross-session isolation, cleanup on stale sessions
  - `test_integration_execution.py` — Code execution: stdout capture, syntax/runtime errors, state persistence, timeout enforcement, display hook capture, namespace reset via real JSON-RPC
  - `test_integration_files.py` — File I/O: write/read text and binary files, directory operations, error handling via docker exec into `/data` named volumes
  - `test_integration_packages.py` — Package installation: `uv pip install`, import and use installed packages, cross-session isolation
  - `test_integration_security.py` — Security constraints: non-root user (UID 1000), read-only root filesystem, network isolation, session filesystem separation
  - `tests/conftest.py` — Session-scoped fixtures for Docker client, image building, and per-test session management
  - `tests/rpc_helpers.py` — `rpc_call()` helper for JSON-RPC communication in tests

- **Docker named volumes for `/data`** — Session `/data` directories now use Docker-managed named volumes instead of host-side bind mounts, avoiding permission errors in Docker-in-Docker scenarios

- **`/tmp` tmpfs mount** — Session containers get a 64MB tmpfs at `/tmp` for temporary file operations

- **`test-integration` Makefile target** — Runs integration tests with `-m integration` marker

### Changed

- **File I/O delegation** — `MCPToolHandler.write_file()`, `read_file()`, and `list_files()` now delegate to `SessionManager` methods that use docker exec to interact with container `/data` volumes, instead of doing host-side filesystem I/O

- **`SessionManager.send_rpc()`** — Now delegates to `RealDockerClient.container_rpc()` which writes requests to the entrypoint's stdin via docker exec and reads responses from container logs (demuxed stdout)

- **Default data directory** — Changed from project-local `data/` to `~/.mcp-sandbox-pyrepl/data/`

- **`create_docker_client()`** — Now wraps the docker-py client in `RealDockerClient` adapter before returning

- **Package installer** — Added `--no-cache` flag to `uv pip install` to reduce image size

- **Pytest configuration** — Integration tests excluded by default (`-m "not integration"`), with explicit `integration` marker

- **README** — Removed MIT license section, minor formatting corrections in architecture diagram

## [0.1.0] — 2026-07-19

### Added

- **MCP Server** — FastMCP-based server exposing 10 MCP tools for sandboxed REPL management:
  - `create_session` — Create sandboxed REPL sessions with configurable Python version or custom Docker image
  - `execute_python` — Execute Python code with captured stdout, stderr, display hook output, and error reporting
  - `install_packages` — Install Python packages via `uv pip install` with temporary network access
  - `list_sessions` / `get_session` — List and inspect active sessions
  - `end_session` — Cleanly terminate sessions (idempotent)
  - `list_python_versions` — List available Python versions and custom images
  - `write_file` / `read_file` / `list_files` — File I/O operations on session data volumes

- **Session Manager** — Docker container lifecycle management:
  - Create sessions with non-root user (UID 1000), read-only root filesystem, and all capabilities dropped
  - Session-scoped `/data` and `/session` volume mounts
  - Network connect/disconnect for secure package installation
  - Session restart on hard timeout corruption
  - Configurable image registry mapping Python versions to Docker images
  - Graceful shutdown via JSON-RPC before container stop

- **Container-side JSON-RPC Server** — stdin/stdout loop running inside each Docker container:
  - `Namespace` — Persistent execution state across `exec` calls with REPL display hook capture
  - `ThreadTimeoutStrategy` — Thread-based timeout enforcement with ctypes async exception fallback
  - `NoOpTimeoutStrategy` — Pass-through strategy for testing
  - `PackageInstaller` — Package installation via `uv pip install` into session-scoped virtual environment
  - Support for `exec`, `install`, `reset`, `ping`, and `shutdown` RPC methods

- **Configuration System** — YAML-based configuration with defaults:
  - Image registry for Python 3.9 through 3.13
  - Configurable default Python version and execution timeout
  - Custom data directory path
  - Command-line argument support (`--config`, `--verbose`)
  - Graceful fallback to defaults on missing or invalid config files

- **Docker Base Image** — `sandbox-base` Dockerfile:
  - Python 3.x slim base with `uv` pre-installed
  - Non-root `sandbox` user (UID 1000)
  - REPL entrypoint script baked in
  - Pre-configured virtual environment at `/session/venv`
  - Build-time Python version parameterization

- **File I/O** — Host-side file operations on session data directories:
  - Write text and binary (base64-encoded) files
  - Read files with automatic text/binary detection
  - List directory contents with file type and size

- **Architecture & Design**:
  - Dependency Injection via `typing.Protocol` (no `mock.patch` in tests)
  - Factory pattern for composition root (config read once, baked into objects)
  - Rich domain models (`SessionMetadata`, `Namespace`, `RPCRequest`, `ExecResult`)
  - Strategy pattern for timeout enforcement
  - Outside-in TDD with behavior-driven tests

- **Test Suite** — 70+ behavior-driven tests organized by component:
  - `FakeDockerClient` and `FakeSessionManager` for host-side testing
  - `FakeTimeoutStrategy` and `FakePackageInstaller` for dispatcher testing
  - Namespace tests covering expressions, print output, state persistence, syntax/runtime errors, multi-line code, imports, and reset
  - Timeout tests covering normal completion, timeout errors, state preservation after timeout
  - Server loop tests covering multi-request processing, shutdown, empty lines, invalid JSON
  - MCP tool tests covering all 10 tools with edge cases
  - Config loading tests with file fallback and merge semantics
  - Signal handler registration tests

- **Development Toolchain**:
  - `uv` for fast dependency management
  - `ruff` for linting and formatting
  - `pytest` with coverage reporting
  - `ty` for static type checking
  - `Makefile` with `install`, `test`, `lint`, `format`, `format-check`, `typecheck`, `check`, `clean` targets
  - Smoke tests verifying the toolchain is correctly installed

- **Documentation**:
  - Design principles document outlining testability-first philosophy
  - OpenSpec specifications for session lifecycle, code execution, sandbox security, data transfer, package management, and image management
  - Docker Compose setup for IDE-based development
