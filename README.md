# mcp-sandbox-pyrepl

> **⚠️ Warning: Learning Project**
>
> This is a **learning project** created to get familiar with [OpenSpec](https://openspec.dev). It is not intended for production use and **will not be actively maintained**. Use at your own risk.

**An MCP server providing a sandboxed, stateful Python REPL via Docker containers.**

`mcp-sandbox-pyrepl` exposes a set of MCP (Model Context Protocol) tools that let AI assistants create isolated Python REPL sessions, execute code with timeouts, install packages, read/write files, and manage the full session lifecycle — all backed by Docker containers with a defense-in-depth security profile.

## Features

- **🗄️ Session Lifecycle** — Create, list, inspect, and terminate sandboxed REPL sessions. Each session is a dedicated Docker container with its own persistent namespace.
- **▶️ Code Execution** — Execute arbitrary Python code with captured stdout, stderr, display hook output, and error reporting (syntax + runtime). Configurable timeout with graceful thread interruption.
- **📦 Package Management** — Install Python packages via `uv pip install` with temporary network access. Session-scoped virtual environments ensure isolation between sessions.
- **📁 File I/O** — Read, write, and list files in each session's persistent `/data` volume. Supports both text and binary content.
- **🐍 Multiple Python Versions** — Built-in support for Python 3.9 through 3.13. Extensible with custom Docker images.
- **🛡️ Sandbox Security** — Non-root user, read-only root filesystem, all Linux capabilities dropped, network isolation during code execution, no host access.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     MCP Client (AI Assistant)               │
└─────────────────────────┬───────────────────────────────────┘
                          │ MCP Protocol (stdio/SSE)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                  MCP Server (FastMCP)                       │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              MCPToolHandler                          │   │
│  │  create_session  execute_python  install_packages    │   │
│  │  list_sessions   get_session     end_session         │   │
│  │  list_python_versions  write_file  read_file  list_files│ │
│  └──────────────────────┬───────────────────────────────┘   │
│                         │ DI (Protocol)                     │
│  ┌──────────────────────▼───────────────────────────────┐   │
│  │              SessionManager                          │   │
│  │  Container lifecycle, network mgmt, session registry │   │
│  └──────────────────────┬───────────────────────────────┘   │
│                         │ DockerClient (Protocol)           │
└─────────────────────────┼───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│             Docker Container (per session)                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  SessionServer (JSON-RPC 2.0 stdin/stdout loop)      │   │
│  │  ┌────────────────────────────────────────────────┐  │   │
│  │  │  RPCDispatcher                                 │  │   │
│  │  │  ┌──────────┐  ┌─────────────────┐  ┌───────┐  │  │   │
│  │  │  │ Namespace│  │ ThreadTimeout   │  │Package│  │  │   │
│  │  │  │ (state)  │  │ Strategy        │  │Installer │  │   │
│  │  │  └──────────┘  └─────────────────┘  └───────┘  │  │   │
│  │  └────────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

The system follows a **clean layered architecture**:

1. **MCP Layer** (`mcp_server.py`) — FastMCP server exposing MCP tools. Receives `SessionManager` via dependency injection.
2. **Host Layer** (`session_manager.py`) — Manages Docker container lifecycle, network isolation, and session metadata. Receives a `DockerClient` Protocol.
3. **Container Layer** (`entrypoint.py`) — JSON-RPC 2.0 server running inside each container. Contains the `Namespace` (persistent execution state), `ThreadTimeoutStrategy` (timeout enforcement), and `PackageInstaller`.

Communication between the host and container happens via JSON-RPC 2.0 over stdin/stdout.

## Design Principles

This project follows strict design principles for testability and maintainability:

- **Testability is the design quality signal** — if a behavior-driven test is hard to write, the design is wrong.
- **Dependency Injection** — all collaborators are injected as constructor parameters. No `mock.patch`.
- **Protocols over inheritance** — consumer-defined `typing.Protocol` interfaces. No coupling to provider types.
- **Factories as composition roots** — config is read once and baked into objects. Intermediate layers never see settings.
- **Rich domain models** — behavior lives with the data it operates on.
- **Outside-in TDD** — write the highest-level test first, design the next layer's interface by what the test needs.

For the full design rationale, see [design-principles.md](.eca/rules/design-principles.md).

## Getting Started

### Prerequisites

- **Python** ≥ 3.10
- **Docker** — installed and running (the `docker` CLI daemon must be accessible)
- **uv** — the Rust-based Python package manager ([install guide](https://docs.astral.sh/uv/#installation))

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd mcp-sandbox-pyrepl

# Install dependencies with uv
uv sync --group dev
```

### Build the Sandbox Base Images

```bash
# Build for each Python version you need
docker build -t sandbox-base:3.12 \
  -f images/sandbox-base/Dockerfile \
  --build-arg PYTHON_VERSION=3.12 .

docker build -t sandbox-base:3.13 \
  -f images/sandbox-base/Dockerfile \
  --build-arg PYTHON_VERSION=3.13 .

# Repeat for 3.9, 3.10, 3.11 as needed
```

### Configuration

Configuration is stored in `config.yaml` at the project root. A default configuration is provided:

```yaml
sandbox:
  images:
    "3.9": "sandbox-base:3.9"
    "3.10": "sandbox-base:3.10"
    "3.11": "sandbox-base:3.11"
    "3.12": "sandbox-base:3.12"
    "3.13": "sandbox-base:3.13"
  defaults:
    python_version: "3.12"
    timeout: 30
  data_dir: "/home/ubuntu/repos/mcp-sandbox-pyrepl/data"
```

You can override the config path with the `--config` flag.

### Run the Server

```bash
# Run the MCP server (stdio mode — use with an MCP client)
uv run mcp-sandbox-pyrepl

# Enable verbose logging
uv run mcp-sandbox-pyrepl --verbose

# Use a custom config file
uv run mcp-sandbox-pyrepl --config /path/to/config.yaml
```

## MCP Tools

| Tool | Description |
|---|---|
| `create_session` | Create a new sandboxed REPL session. Specify `python_version` (e.g., `"3.12"`) or a custom `image`. |
| `execute_python` | Execute Python code in a session. Returns `stdout`, `stderr`, `display`, and `error`. Configurable `timeout` (default: 30s). |
| `install_packages` | Install Python packages via `uv`. Temporarily enables network access. |
| `list_sessions` | List all active sessions with metadata. |
| `get_session` | Get details about a specific session. |
| `end_session` | Terminate a session and clean up the container. Idempotent. |
| `list_python_versions` | List available Python versions and custom images. |
| `write_file` | Write content to a file in the session's data directory. Supports text and base64-encoded binary. |
| `read_file` | Read a file from the session's data directory. Returns text or base64-encoded binary. |
| `list_files` | List files in the session's data directory. |

## Development

### Toolchain

- **pytest** — test runner with coverage (`pytest-cov`)
- **ruff** — linter and formatter
- **ty** — static type checker

```bash
# Run all checks
make check

# Or individually
make test        # Run all tests with coverage (unit + integration)
make test-unit   # Run unit tests only (fast, no Docker needed)
make test-integration        # Run integration tests serially
make test-integration-parallel  # Run integration tests in parallel
make test-optimized-speed  # Run integration first unit tests and then integration tests in parallel
make lint        # Run ruff linter
make format      # Format code with ruff
make typecheck   # Run type checker (ty)
make check-all   # Formats code and performs all available checks
make clean       # Clean up caches and artifacts
```

### Project Structure

```
mcp-sandbox-pyrepl/
├── src/
│   ├── __init__.py
│   ├── main.py                  # Entry point, factories, wiring
│   ├── mcp_server.py            # FastMCP tool handlers
│   ├── session_manager.py       # Docker container lifecycle
│   └── entrypoint.py            # Container-side JSON-RPC server
├── tests/
│   ├── unit/
│   │   ├── test_entrypoint_dispatcher.py   # JSON-RPC routing
│   │   ├── test_entrypoint_namespace.py    # Code execution namespace
│   │   ├── test_entrypoint_server.py       # stdin/stdout loop
│   │   ├── test_entrypoint_timeout.py      # Timeout strategy
│   │   ├── test_main.py             # Config loading, signals
│   │   └── test_toolchain.py        # Dev toolchain smoke tests
│   └── integration/
│       ├── conftest.py               # Docker fixtures (session_manager, class_container)
│       ├── rpc_helpers.py            # JSON-RPC helpers for container communication
│       ├── test_execution.py         # Code execution inside containers
│       ├── test_files.py             # File I/O via /data volume
│       ├── test_main.py              # Factory functions (create_session_manager, create_mcp_app)
│       ├── test_mcp_server.py        # MCP tool handler behavior
│       ├── test_packages.py          # Package installation
│       ├── test_security.py          # Security constraints (non-root, network isolation)
│       ├── test_session.py           # Session lifecycle (create, list, get, end)
│       └── test_session_manager.py   # Session manager with real Docker
├── images/
│   └── sandbox-base/
│       └── Dockerfile           # Base Docker image definition
├── docker-ide/
│   ├── Dockerfile               # IDE container for development
│   ├── docker-compose.yaml
│   ├── Makefile
│   └── entrypoint.sh
├── openspec/                    # OpenSpec specification documents
├── config.yaml                  # Server configuration
├── pyproject.toml               # Project metadata and tool config
├── Makefile                     # Development task runner
├── README.md
└── CHANGELOG.md
```

### Testing Philosophy

All tests follow behavior-driven, outside-in TDD:

- **No `mock.patch`** — dependencies are injected via Protocols. Tests use fakes (e.g., `FakeSessionManager`, `FakeDockerClient`).
- **1–3 line arrange phase** — if the setup is longer, the design needs refactoring.
- **Behavior, not implementation** — tests specify what the code does, not how it does it.
