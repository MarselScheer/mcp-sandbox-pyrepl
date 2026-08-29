## Why

`container_rpc()` currently uses a two-legged approach: a `docker exec` subprocess writes to `/proc/1/fd/0` for the send side, and `container.logs()` with polling/backoff for the read side. This is fragile (`tail=5` can miss responses), adds latency (10–100ms polling), and spawns a subprocess per call. The recently improved `container_stdin()` proved we can reliably extract a raw `socket.socket` from `attach_socket()` — and the socket is bidirectional. This change replaces both legs with a single attach socket used for write (raw bytes to stdin) and read (parse Docker's multiplexed frame headers), eliminating the subprocess, the polling, and the `tail=5` race.

## What Changes

- **`RealDockerClient.container_rpc()`** — rewritten to use `attach_socket()` bidirectionally instead of `docker exec` + `container.logs()` polling.
- **`RealDockerClient._attach_raw_socket()`** — new private helper that extracts a raw `socket.socket` from `attach_socket()` (handling `socket.SocketIO` unwrapping). Reused by both `container_stdin()` and the new `container_rpc()`.
- **`RealDockerClient.container_stdin()`** — refactored to delegate to `_attach_raw_socket()` instead of duplicating the unwrapping logic.
- **`DockerClient` Protocol** — unchanged (no behavior change).
- **`SessionManager`** — unchanged (no behavior change).

## Capabilities

### New Capabilities

*(none — pure implementation refactoring)*

### Modified Capabilities

*(none — no spec-level behavior changes)*

## Impact

- **Affected file:** `src/docker_adapter.py` — rewritten `container_rpc()`, new `_attach_raw_socket()` helper, refactored `container_stdin()`.
- **New dependencies:** `struct` (for frame header parsing — already stdlib, no added dependency).
- **Removed dependencies:** `time` (no more polling loop), `json` — wait, `json` is still needed for serialization.
- **Performance:** Subprocess per call eliminated (~O(1) overhead → ~0). Polling eliminated (latency 10–100ms → sub-ms response on socket). Calls become truly synchronous with socket timeout instead of a manual backoff loop.
- **Integration tests:** Existing `container_rpc` tests continue to pass unchanged. Optionally add a test for the `_attach_raw_socket` helper.