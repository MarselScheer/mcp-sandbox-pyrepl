## 1. Project Setup

- [x] 1.1 Create project structure: `src/`, `images/sandbox-base/`, `config.yaml`, `pyproject.toml`
- [x] 1.2 Add dependencies: `mcp`, `docker-py`, `pyyaml` to `pyproject.toml`
- [x] 1.3 Create `config.yaml` with image registry, default settings, and data directory path

## 2. Base Docker Image

- [x] 2.1 Create `images/sandbox-base/Dockerfile` — Python 3.x slim base, install `uv`, create `sandbox` user (UID 1000), copy entrypoint
- [x] 2.2 Create `src/entrypoint.py` — JSON-RPC 2.0 loop over stdin/stdout (Dockerfile copies from src/)

## 3. REPL Entrypoint (Inside Container)

- [x] 3.1 Implement JSON-RPC dispatcher: parse requests, route to handler methods, write responses
- [x] 3.2 Implement `exec` method — compile code, exec in persistent `_namespace` dict, capture stdout/stderr/display
- [x] 3.3 Implement execution timeout — thread + async exception via `PyThreadState_SetAsyncExc` with fallback corruption flag
- [x] 3.4 Implement `install` method — run `uv pip install` for requested packages in session venv
- [x] 3.5 Implement `reset` method — clear `_namespace` dict, keep venv intact
- [x] 3.6 Implement `ping` and `shutdown` methods — health check and graceful exit

## 4. Session Manager (Host Side)

- [x] 4.1 Implement `SessionManager` class — registry of active sessions, mapping session_id to container metadata
- [x] 4.2 Implement `create_session` — `docker run` with security profile (read-only rootfs, non-root user, cap-drop ALL, /data + /session volumes)
- [x] 4.3 Implement package pre-installation after container start — temp network connect, uv install, network disconnect
- [x] 4.4 Implement `end_session` — send shutdown, docker stop + rm, clean up /data directory
- [x] 4.5 Implement `list_sessions` and `get_session` — query active session registry
- [x] 4.6 Implement network connect/disconnect helpers for package installation
- [x] 4.7 Implement container restart on corruption — detect session_corrupted flag, kill old container, start fresh

## 5. MCP Server (FastMCP)

- [x] 5.1 Create `src/mcp_server.py` — FastMCP app with all tools registered
- [x] 5.2 Implement `create_session` tool — delegates to SessionManager, returns session_id
- [x] 5.3 Implement `execute_python` tool — sends JSON-RPC exec to container, returns result
- [x] 5.4 Implement `install_packages` tool — network connect, send JSON-RPC install, network disconnect
- [x] 5.5 Implement `list_sessions` and `get_session` tools — query registry
- [x] 5.6 Implement `end_session` tool — delegates to SessionManager

## 6. Data Transfer

- [x] 6.1 Implement `write_file` tool — write content to host-side `/data/<session_id>/<path>`
- [x] 6.2 Implement `read_file` tool — read content from host-side `/data/<session_id>/<path>`, return as text or base64
- [x] 6.3 Implement `list_files` tool — list files in `/data/<session_id>/<path>`

## 7. Integration and Polish

- [x] 7.1 Wire everything together in `src/main.py` — load config, init SessionManager, start FastMCP server
- [x] 7.2 Add server startup — detect Docker availability, load image registry, print startup banner
- [x] 7.3 Add graceful shutdown — end all active sessions on SIGINT/SIGTERM
- [x] 7.4 Add orphan cleanup — detect and clean up orphaned containers on startup
- [x] 7.5 Create `README.md` — already exists with basic project info