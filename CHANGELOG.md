# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
