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

One socket for stdin (write-only, already exists as `container_stdin()`), one for stdout (read-only, new). The stdout socket uses `params={stdout: 1, stream: 1}` — a single stream, so Docker does NOT apply the 8-byte multiplexing header.

**Alternatives considered:**

| Approach | Read side | Pros | Cons |
|---|---|---|---|
| **Two sockets** (stdin + stdout) | Raw, no headers | Simple `readline()`, no frame parsing | Two attach calls |
| **One socket** (stdin + stdout) | Multiplexed with 8-byte headers | Single connection | Need frame parser for 8-byte headers, significantly more complex |
| **One socket** (stdin + stdout, stderr excluded) | Unknown — Docker may still multiplex | Could be simpler | Unpredictable behavior, need to test |
| **Current approach** (exec + logs) | Logs demuxed by Docker | Works (mostly) | Race condition + fragile heuristic |

**Rationale:** Two sockets is the simplest approach that eliminates the race condition and log-parsing. The overhead of two `attach_socket` calls per request is negligible. The stdin socket already exists (`container_stdin()`) and can be reused or a new one created per call.

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
| `attach_socket` with `stdout:1` alone still adds 8-byte headers | Low (Docker only multiplexes when both stdout+stderr are attached) | Read side would get garbage bytes | Verify in first task with a spike test. If headers are present, switch to a frame-stripping reader. |
| Socket close can race with container shutdown | Medium | ConnectionError propagated to consumer | `_send_shutdown` uses its own `attach_socket` call (stdin-only), which is unaffected. If the container dies mid-RPC, `readline()` returns empty string (EOF) → clean ConnectionError. |
| Entrypoint stdout has multiple lines (e.g., Python startup banner) | Low (entrypoint uses `python -c` or `python /entrypoint.py` with no banner) | First read might get non-JSON line | Use a `readline()` loop: skip non-JSON lines, return the first valid JSON object. The entrypoint only writes one JSON line per request, so this handles any bootstrap output. |
| Performance: two `attach_socket` calls per RPC adds latency | Low (HTTP attach handshake is ~1ms locally) | Not noticeable for code execution (100ms+) | Acceptable. If profiling ever shows this as a bottleneck, switch to keep-alive sockets. |