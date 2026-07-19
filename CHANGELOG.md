# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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