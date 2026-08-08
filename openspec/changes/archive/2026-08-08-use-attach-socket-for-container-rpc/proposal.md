## Why

`RealDockerClient.container_rpc()` currently communicates with the container's JSON-RPC entrypoint via two separate, fragile mechanisms: (1) writing the request via a `docker exec` subprocess that opens `/proc/1/fd/0`, and (2) reading the response from `container.logs()` with a `time.sleep(0.3)` race condition. The TODO in the code explicitly calls this out as a race condition. This approach is fragile, unreliable under load, and couples the communication path to Linux kernel details (PID namespaces, `/proc` filesystem).

## What Changes

Replace the two-path `exec→/proc/1/fd/0` + `container.logs()` approach in `RealDockerClient.container_rpc()` with a hybrid approach that keeps the proven write path but replaces the fragile read path:

- **Write** (request → container stdin): Keep `docker exec sh -c echo '...' > /proc/1/fd/0` — proven reliable via shell redirection (the Python `open()` approach failed, but shell `echo` with `>` works)
- **Read** (stdout → response): Replace `container.logs()` with a stdout-only `attach_socket` + `_DockerFrameReader` that blocks until the response arrives — no race condition, no sleep

This gives us:

- **Reliable request-response pairing**: The socket `read()` blocks until the response arrives — no race condition, no sleep
- **Clean separation**: User code stdout is captured by the entrypoint's `StringIO` redirect and returned inside the JSON response — the attach socket stream only carries the JSON-RPC response
- **No log-parsing heuristic**: Drops the fragile "last JSON line" parsing from `container.logs()`
- **Minimal `/proc` manipulation**: The `/proc/1/fd/0` write path uses shell redirection (via `sh -c echo`), not a separate `open()` call in a Python subprocess — simpler and more reliable

The entrypoint (`entrypoint.py`) remains completely unchanged — it still reads from stdin and writes to stdout.

No new capabilities are introduced and no spec-level behavior changes (pure implementation refactor).

## Capabilities

This is a pure refactor with no spec-level behavior changes. `skip_specs: true` is set in `.openspec.yaml`.

## Impact

- **`src/docker_adapter.py`** (`RealDockerClient`): `container_rpc()` rewritten; `container_stdin()` may be simplified or kept as-is for shutdown. The source adapter (in `src/`) and the test adapter (in `tests/` — a copy) both need updating.
- **`tests/docker_adapter.py`** (test copy of `RealDockerClient`): Same changes as the source adapter.
- **`tests/test_session_manager.py`** (`FakeDockerClient`): `container_rpc()` behavior may need updating in the fake if the interface changes (e.g., different error types).
- **No changes** to: `entrypoint.py`, `session_manager.py`, `mcp_server.py`, `Dockerfile`, tests beyond the adapter layer.