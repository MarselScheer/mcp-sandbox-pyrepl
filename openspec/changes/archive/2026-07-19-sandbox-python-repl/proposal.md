## Why

AI coding assistants (Claude, Cursor, etc.) need a safe way to execute Python code — for data analysis, testing snippets, exploring APIs, and getting documentation. Running code directly on the host is a security risk, and there's currently no MCP server that provides a sandboxed, stateful Python REPL with version management and package isolation.

This change introduces an MCP server that gives AI assistants a sandboxed Python execution environment — safe by design, stateful across calls, and flexible enough to handle real data analysis workflows.

## What Changes

- **New MCP server** (`mcp-sandbox-pyrepl`) exposes Python execution tools to AI clients via the Model Context Protocol, built with `FastMCP`
- **Docker-based sandbox** isolates code execution from the host machine with read-only rootfs, non-root user, and dropped capabilities
- **Network isolation** ensures only `uv` package installation has network access; executed Python code runs without network
- **Stateful REPL sessions** persist variables and execution history within each container's lifetime
- **Data transfer** via a mounted `/data` volume with dedicated tools for reading and writing files
- **Multi-version Python support** via versioned Docker images (`sandbox-base:3.9` through `sandbox-base:3.13`)
- **Custom image support** allows users to extend the base sandbox image with pre-installed tools
- **Package management** via `uv`, installable per-session with network temporarily enabled

## Capabilities

### New Capabilities

- **session-lifecycle**: Create, manage, and clean up sandboxed REPL sessions, each backed by a Docker container
- **code-execution**: Execute arbitrary Python code within a persistent namespace, capturing stdout/stderr/errors and returning display output
- **package-management**: Install Python packages via `uv` in a session, with automatic network isolation (net on during install, net off during execution)
- **data-transfer**: Transfer files into and out of the sandbox via a mounted `/data` volume, enabling data analysis workflows
- **sandbox-security**: Enforce execution isolation via Docker — read-only rootfs, non-root user, dropped capabilities, and network removal during code execution
- **image-management**: Define and manage base sandbox images per Python version, supporting custom user-built images

### Modified Capabilities

*None — this is a new project.*

## Impact

- **New code**: MCP server in `src/`, base Docker image in `images/sandbox-base/`, configuration in `config.yaml`
- **Dependencies**: `mcp` (FastMCP), `docker-py` (Docker API client), Docker runtime on the host
- **Existing infra**: The `docker-ide/` directory is unchanged — this is additive
- **Security**: No code executes on the host; all execution happens inside Docker containers with network isolation