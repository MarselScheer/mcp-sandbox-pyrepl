## 1. Shared helper: `_attach_raw_socket()`

- [x] 1.1 Add `_attach_raw_socket()` private method to `RealDockerClient` — extracts a raw `socket.socket` from `container.attach_socket()`, handling `SocketIO` unwrapping via `._sock`
- [x] 1.2 Refactor `container_stdin()` to delegate to `_attach_raw_socket()` instead of duplicating the unwrapping logic

## 2. Rewrite `container_rpc()` to use attach socket

- [x] 2.1 Add `_recv_exact()` helper — reads exactly N bytes from a socket (partial-read-aware loop)
- [x] 2.2 Add `_read_frame()` helper — reads one Docker-multiplexed frame (8-byte header + payload), returns `(stream_type, payload)` or `None`
- [x] 2.3 Rewrite `container_rpc()` — use `_attach_raw_socket(params={"stdin": 1, "stdout": 1, "stderr": 1, "stream": 1, "logs": 1})`, `sendall()` for the request, blocking `recv()` with `sock.settimeout()` for the response
- [x] 2.4 Remove `import time` from `docker_adapter.py` if no longer used elsewhere
- [x] 2.5 Run existing integration tests to confirm no regressions

## 3. Update integration tests

- [x] 3.1 Run the existing `test_session_manager.py` integration tests to verify `container_rpc()` still works via `send_rpc()`
- [x] 3.2 Run `test_main.py` and `test_mcp_server.py` integration tests to verify the full MCP tool chain