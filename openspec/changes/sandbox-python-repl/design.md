## Context

MCP Sandbox PyREPL provides AI assistants with a safe, stateful Python execution environment. The system comprises three layers:

1. **MCP Server** (host process, FastMCP) — exposes tools to AI clients and manages container lifecycle
2. **Docker containers** (sandbox) — isolated execution environments, one per session
3. **REPL entrypoint** (inside container) — JSON-RPC process that receives code and returns results

The host must have Docker installed. No code executes on the host itself.

## Goals / Non-Goals

**Goals:**
- AI assistants can execute Python code in an isolated sandbox with no host access
- Sessions maintain state (variables, history) across multiple `execute_python` calls within the container's lifetime
- Data can be transferred into (`write_file`) and out of (`read_file`) the sandbox via a mounted volume
- Multiple Python versions (3.9–3.13) are available via versioned Docker images
- Packages are installable per-session using `uv`, with network removed during code execution
- Custom Docker images are supported for users with pre-configured environments
- Timeouts on code execution prevent infinite loops from hanging the session

**Non-Goals:**
- Persisting sessions across container restarts (in-container persistence only)
- Cross-session variable sharing (each session is isolated)
- A web UI or dashboard
- Jupyter notebook integration
- Running on Windows natively (Docker required)
- Multi-tenant isolation between sessions (each container is single-tenant already)

## Decisions

### Decision 1: FastMCP over raw MCP SDK
**Chosen:** FastMCP (`from mcp.server.fastmcp import FastMCP`)

FastMCP provides a declarative, decorator-based API for defining tools, resources, and prompts — similar to FastAPI. It reduces boilerplate and improves readability versus the low-level `Server` class from the MCP SDK.

**Alternatives considered:**
- **Low-level `mcp.server.Server`**: More control but significantly more verbose. No benefit for this use case.
- **Custom protocol implementation**: Unnecessary — MCP is the standard for AI tool exposure.

### Decision 2: Docker with network connect/disconnect for isolation
**Chosen:** Start containers with network, run `uv install`, disconnect network, run code

```python
# Pseudocode
container = docker.run(image, network="bridge")
container.exec(["uv", "pip install", pkg])   # network: YES
docker.network_disconnect("bridge", container)  # network: GONE
container.stdin.write(json_rpc_request)       # code runs with NO network
```

When additional packages are needed mid-session, the cycle repeats: connect → install → disconnect.

**Alternatives considered:**
- **iptables/nftables inside container**: More complex, harder to reason about, error-prone.
- **Two containers (build + run)**: More overhead, session state sharing complexity.
- **Subprocess with unshare**: Weaker isolation, no Docker security profile.

### Decision 3: Long-running REPL with JSON-RPC over stdin/stdout
**Chosen:** A single Python process runs inside the container, reading JSON-RPC 2.0 requests from stdin and writing responses to stdout. The process maintains a persistent `_namespace` dict that accumulates state across `exec` calls.

**Protocol (internal, between MCP server and container):**

**Requests:**
```json
{"jsonrpc":"2.0","id":1,"method":"exec","params":{"code":"x = 42"}}
{"jsonrpc":"2.0","id":2,"method":"exec","params":{"code":"print(x * 2)"}}
{"jsonrpc":"2.0","id":3,"method":"install","params":{"packages":[{"name":"pandas","version":"2.0.0"}]}}
{"jsonrpc":"2.0","id":4,"method":"reset","params":{}}
{"jsonrpc":"2.0","id":5,"method":"ping","params":{}}
```

**Responses:**
```json
{"jsonrpc":"2.0","id":1,"result":{"stdout":"","stderr":"","display":[],"error":null}}
```

**Alternatives considered:**
- **Unix socket**: More complex setup, unnecessary for single-container communication.
- **HTTP within container**: Heavier, adds HTTP server dependency to the entrypoint.
- **Shared filesystem for IPC**: Race conditions, polling overhead.

### Decision 4: Thread + async exception for execution timeouts
**Chosen:** Run each `exec` in a `threading.Thread`. The main thread waits with `thread.join(timeout=N)`. On timeout, inject `TimeoutError` via `PyThreadState_SetAsyncExc` (ctypes). If the thread still doesn't die, return a `session_corrupted` flag to the MCP server, which will restart the container.

```python
_thread = threading.Thread(target=_exec_in_namespace, args=(code,))
_thread.start()
_thread.join(timeout=TIMEOUT)

if _thread.is_alive():
    _raise_async_exc(_thread.ident, _TimeoutError)  # ctypes hack
    _thread.join(timeout=5)
    if _thread.is_alive():
        return {"session_corrupted": True, "error": "Execution timed out"}
```

**Alternatives considered:**
- **Fork per execution**: Clean signal-based timeout, but fork+COW means child namespace changes are lost.
- **Subprocess per execution + pickle namespace**: Robust but adds serialization overhead and can't pickle all objects.
- **Single-threaded with signal.alarm**: Signals only work in main thread, interferes with stdin reading.

### Decision 5: uv for package management
**Chosen:** `uv` is fast (Rust-based drop-in for pip), handles virtual environments well, and the user specifically requested it.

The base image installs `uv`. Each session gets its own virtual environment managed by uv. `uv pip install` is called with network connected, then the network is removed.

### Decision 6: Session-level virtual environments
**Chosen:** Each session gets its own uv-managed virtual environment at `/session/venv/`. This prevents package conflicts between sessions and allows clean isolation even if they share the same Python version.

### Decision 7: Configuration-driven image registry
**Chosen:** A `config.yaml` maps Python version strings to Docker image names:

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

Users add custom images by extending the mapping: `"my-ds": "my-data-sandbox:latest"`.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| **Thread timeout doesn't kill the thread** — `PyThreadState_SetAsyncExc` is a CPython implementation detail and can fail, especially with C extensions (numpy, pandas) that hold the GIL | Return `session_corrupted` flag; MCP server kills and restarts the container on next request |
| **Docker container resource leak** — if the MCP server crashes, containers may keep running | Register cleanup on shutdown; orphaned container detection on startup |
| **uv install is slow** — especially for large packages like `torch` | User can pre-build custom images with their packages already installed |
| **Namespace object bloat** — large DataFrames in memory consume container RAM | No hard fix, but per-session containers mean one user's bloat doesn't affect others |
| **Docker not available** — the sandbox requires a Docker daemon | Fail fast with a clear error message; document the prerequisite |
| **Pickle-incompatible objects in namespace** — cannot serialize some state | Don't use pickle for cross-exec persistence; keep state in-memory only. On timeout/restart, the namespace is lost. |

## Open Questions

*None — all decisions have been resolved during the exploration phase.*
