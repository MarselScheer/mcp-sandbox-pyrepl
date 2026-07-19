## 1. Project Setup

- [ ] 1.1 Create project structure: `src/`, `images/sandbox-base/`, `config.yaml`, `pyproject.toml`
- [ ] 1.2 Add dependencies: `mcp`, `docker-py`, `pyyaml` to `pyproject.toml`
- [ ] 1.3 Create `config.yaml` with image registry, default settings, and data directory path

## 2. Base Docker Image

- [ ] 2.1 Create `images/sandbox-base/Dockerfile` — Python 3.x slim base, install `uv`, create `sandbox` user (UID 1000), copy entrypoint
- [ ] 2.2 Create `images/sandbox-base/entrypoint.py` — JSON-RPC 2.0 loop over stdin/stdout

## 3. REPL Entrypoint (Inside Container)

- [ ] 3.1 Implement JSON-RPC dispatcher: parse requests, route to handler methods, write responses
- [ ] 3.2 Implement `exec` method — compile code, exec in persistent `_namespace` dict, capture stdout/stderr/display
- [ ] 3.3 Implement execution timeout — thread + async exception via `PyThreadState_SetAsyncExc` with fallback corruption flag
- [ ] 3.4 Implement `install` method — run `uv pip install` for requested packages in session venv
- [ ] 3.5 Implement `reset` method — clear `_namespace` dict, keep venv intact
- [ ] 3.6 Implement `ping` and `shutdown` methods — health check and graceful exit

## 4. Session Manager (Host Side)

- [ ] 4.1 Implement `SessionManager` class — registry of active sessions, mapping session_id to container metadata
- [ ] 4.2 Implement `create_session` — `docker run` with security profile (read-only rootfs, non-root user, cap-drop ALL, /data + /session volumes)
- [ ] 4.3 Implement package pre-installation after container start — temp network connect, uv install, network disconnect
- [ ] 4.4 Implement `end_session` — send shutdown, docker stop + rm, clean up /data directory
- [ ] 4.5 Implement `list_sessions` and `get_session` — query active session registry
- [ ] 4.6 Implement network connect/disconnect helpers for package installation
- [ ] 4.7 Implement container restart on corruption — detect session_corrupted flag, kill old container, start fresh

## 5. MCP Server (FastMCP)

- [ ] 5.1 Create `src/mcp_server.py` — FastMCP app with `@mcp.tool()` decorators for all tools
- [ ] 5.2 Implement `create_session` tool — delegates to SessionManager, returns session_id
- [ ] 5.3 Implement `execute_python` tool — sends JSON-RPC exec to container, returns result
- [ ] 5.4 Implement `install_packages` tool — network connect, send JSON-RPC install, network disconnect
- [ ] 5.5 Implement `list_sessions` and `get_session` tools — query registry
- [ ] 5.6 Implement `end_session` tool — delegates to SessionManager

## 6. Data Transfer

- [ ] 6.1 Implement `write_file` tool — write content to host-side `/data/<session_id>/<path>`
- [ ] 6.2 Implement `read_file` tool — read content from host-side `/data/<session_id>/<path>`, return as text or base64
- [ ] 6.3 Implement `list_files` tool — list files in `/data/<session_id>/<path>`

## 7. Integration and Polish

- [ ] 7.1 Wire everything together in `src/main.py` — load config, init SessionManager, start FastMCP server
- [ ] 7.2 Add server startup — detect Docker availability, load image registry, print startup banner
- [ ] 7.3 Add graceful shutdown — end all active sessions on SIGINT/SIGTERM
- [ ] 7.4 Add orphan cleanup — detect and clean up orphaned containers on startup
- [ ] 7.5 Create `README.md` with usage instructions, prerequisites, image building guide