## Context

See [proposal.md](./proposal.md) for motivation — this doc covers HOW.

`RealDockerClient.container_rpc()` currently communicates with the container's entrypoint (PID 1, running `entrypoint.py`) using a two-path approach:

1. **Write**: `docker exec` → Python script → `open('/proc/1/fd/0', 'w')` → PID 1 stdin
2. **Read**: `container.logs()` → find last JSON line → parse

The entrypoint (`SessionServer` in `entrypoint.py`) is a simple stdin/stdout loop: read a JSON-RPC request line from stdin, dispatch, write one JSON-RPC response line to stdout.

The current approach has a `time.sleep(0.3)` race condition (documented TODO) and relies on log-parsing heuristics that are fragile under load or when user code outputs JSON-like text to stdout (though the `StringIO` capture in `Namespace.exec()` mitigates this for user code).

## Goals / Non-Goals

**Goals:**
- Reliable request-response pairing — no race condition, no sleep
- Replace `docker exec` → `/proc/1/fd/0` writing with Docker's standard `attach_socket` API
- Replace `container.logs()` parsing with direct socket reads
- Keep `entrypoint.py` unchanged (still reads from stdin, writes to stdout)
- Clean error propagation back through SessionManager → MCP handler

**Non-Goals:**
- No changes to the JSON-RPC protocol or request/response format
- No changes to the entrypoint's behavior or internal architecture
- No changes to session lifecycle, code execution, or error reporting semantics
- Not converting to a persistent keep-alive connection (per-request is fine)

## Decisions

### Decision 1: Two attach sockets (stdin + stdout separate) instead of one combined socket

**Chosen: Two sockets.**

One socket for stdin (write-only, already exists as `container_stdin()`), one for stdout (read-only, new). The stdout socket uses `params={stdout: 1, stream: 1}`.

**⚠ Updated understanding (spike verified):** Docker multiplexes even with `stdout: 1` alone. Each frame has an 8-byte header (stream type [1] + pad [3] + payload length [4]). The stdout stream type is `1`. A `_DockerFrameReader` helper strips headers and returns only the stdout payload.

**Alternatives considered:**

| Approach | Read side | Pros | Cons |
|---|---|---|---|
| **Two sockets** (stdin + stdout) | 8-byte frame headers | Simple `readline()` on payload, strip-frame reader | Two attach calls + frame parsing |
| **One socket** (stdin + stdout) | Multiplexed with 8-byte headers | Single connection | Need frame parser for all streams, significantly more complex |
| **Current approach** (exec + logs) | Logs demuxed by Docker | Works (mostly) | Race condition + fragile heuristic |

**Rationale:** Two sockets still wins — the frame parsing is a simple 8-byte header strip per frame, which is straightforward. A single combined socket would need to interleave stdin/stdout writes/reads in a multiplexed stream, which is significantly harder. The overhead of two `attach_socket` calls per request is negligible.

### Decision 2: Per-request socket lifecycle

**Chosen: Create sockets per `container_rpc()` call, close after response.**

Each RPC call opens a fresh stdout `attach_socket`, reads one line, and closes it.

**Alternatives considered:**
- **Keep-alive**: Open sockets once and reuse. Would need reconnection logic, health checks, and lifecycle management. Over-engineered for a REPL where calls are infrequent.
- **Persistent session-level socket**: One socket per container lifetime. More efficient but more complex to manage (container restart, network issues, cleanup).

**Rationale:** Per-request is simple, stateless, and resilient. The overhead of an HTTP attach handshake per call is negligible compared to code execution time (typically 100ms+).

### Decision 3: Timeout via `socket.settimeout()` + fallback to `container.logs()`

**Chosen: `socket.settimeout()` on the stdout socket with a configurable timeout.**

If the container's entrypoint hangs (e.g., infinite loop in user code), `readline()` would block forever. Setting a timeout on the socket ensures we eventually fail cleanly.

If a timeout occurs, we fall back to checking `container.logs()` as a last resort — the entrypoint might have written the response but the socket didn't deliver it in time. This is a safety net, not the primary path.

**Rationale:** The timeout should be generous (e.g., `timeout_seconds + 5`) relative to the execution timeout, since the response should arrive immediately after the code finishes. It's a safety net for edge cases (container under extreme load, kernel scheduling anomalies), not the normal flow.

## Risks / Trade-offs

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `attach_socket` with `stdout:1` alone still adds 8-byte headers | **HIGH (confirmed by spike)** | Read side must strip 8-byte frame headers | Use `_DockerFrameReader` helper that reads header, extracts payload length, and returns only stdout payload bytes. |
| Socket close can race with container shutdown | Medium | ConnectionError propagated to consumer | `_send_shutdown` uses its own `attach_socket` call (stdin-only), which is unaffected. If the container dies mid-RPC, `readline()` returns empty string (EOF) → clean ConnectionError. |
| Entrypoint stdout has multiple frames (split across multiple TCP segments) | Low for small JSON responses, possible for large responses | Read might get partial JSON | Buffer all stdout frames until we have a complete JSON object. The `_DockerFrameReader` concatenates all payloads from stdout frames. |
| Performance: two `attach_socket` calls per RPC adds latency | Low (HTTP attach handshake is ~1ms locally) | Not noticeable for code execution (100ms+) | Acceptable. If profiling ever shows this as a bottleneck, switch to keep-alive sockets. |

## Spike Findings

### Task 1.1: `attach_socket(params={stdout: 1, stream: 1})` — header verification

**Finding: 8-byte frame headers ARE present even with stdout only.**

The spike script confirmed:
- Output: `\x01\x00\x00\x00\x00\x00\x004{"jsonrp`
- Byte 0 (`\x01`): stream type = 1 (stdout)
- Bytes 1–3: padding (zeros)
- Bytes 4–7 (`\x00\x00\x004` = 52): payload length
- After header: JSON payload begins

**Action:** Implement `_DockerFrameReader` that reads the 8-byte header, extracts the payload length, reads exactly that many bytes, and returns only the stdout payload. Skip non-stdout frames (e.g., stderr = stream type 2).

### Task 1.1b: `exec_run` write to `/proc/1/fd/0`

**Finding: Fails with `OSError: [Errno 22] Invalid argument`.**

The old approach of writing via `docker exec` → `/proc/1/fd/0` fails in this environment. Likely causes:
- Container's read-only rootfs preventing `open('/proc/1/fd/0', 'w')` from working
- Kernel-level restrictions on writing to another process's file descriptors

**Action:** Use `container_stdin()` (attach_socket with `params={stdin: 1, stream: 1}`) for writing, which is the standard Docker API for this. This was already planned — the spike just confirms the old path is also broken.