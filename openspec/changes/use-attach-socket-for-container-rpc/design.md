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
- Keep `docker exec` → `/proc/1/fd/0` for writing (proven reliable via shell `echo`), but replace `container.logs()` reading with direct attach socket reads — eliminating the `time.sleep(0.3)` race condition
- Replace `container.logs()` parsing with direct socket reads
- Keep `entrypoint.py` unchanged (still reads from stdin, writes to stdout)
- Clean error propagation back through SessionManager → MCP handler

**Non-Goals:**
- No changes to the JSON-RPC protocol or request/response format
- No changes to the entrypoint's behavior or internal architecture
- No changes to session lifecycle, code execution, or error reporting semantics
- Not converting to a persistent keep-alive connection (per-request is fine)

## Decisions

### Decision 1: Hybrid approach — exec for writing, attach socket for reading

**Chosen: Hybrid approach.**

The `container_rpc()` method uses two different mechanisms:
1. **Write**: `docker exec sh -c echo '...' > /proc/1/fd/0` to write the JSON-RPC request to the entrypoint's stdin.
2. **Read**: `attach_socket(params={stdout: 1, stream: 1})` to read Docker-multiplexed frames (8-byte headers) from the container's stdout, decoded by `_DockerFrameReader`.

**Why a combined attach socket (stdin + stdout) proved unworkable (implementation finding):**

A combined `attach_socket(params={stdin: 1, stdout: 1, stream: 1})` returns a `socket.SocketIO`. While the underlying raw socket (via `_sock`) can be extracted for writing, data written to it **does not reach the container's stdin** in this Docker setup. Confirmed by spike: even a simple Python echo process (`python3 -u -c "for line in sys.stdin: print(line)"`) failed to receive data written via the combined attach socket's raw socket.

**Why exec `echo > /proc/1/fd/0` works (spike verified):**

The old approach of writing via `docker exec` → `open('/proc/1/fd/0', 'w')` using a Python one-liner fails with `OSError: [Errno 22] Invalid argument` (confirmed by the initial spike). However, using **shell** redirection via `docker exec sh -c echo '...' > /proc/1/fd/0` works reliably. The shell's `echo` built-in opens the PID 1 stdin file descriptor via the shell's own `/proc` access, not via an `open()` call in a separate Python process, which avoids the OSError.

**⚠ Multiplexing (spike verified):** Docker multiplexes stdout even on a stdout-only attach socket. Each frame has an 8-byte header (stream type [1] + pad [3] + payload length [4]). The stdout stream type is `1`. A `_DockerFrameReader` helper strips headers and returns only the stdout payload.

**Alternatives considered:**

| Approach | Read side | Write side | Pros | Cons |
|---|---|---|---|---|
| **Hybrid** (exec write + socket read) | `_DockerFrameReader` on stdout `SocketIO` — blocks until response arrives | `exec sh -c echo > /proc/1/fd/0` — proven reliable | No race condition; no log-parsing heuristics; stdin writes actually work | Still uses `/proc` file system for writing |
| **Combined socket** (stdin + stdout) | `_DockerFrameReader` on combined `SocketIO` | `makefile("wb")` on raw socket | Single connection, conceptually clean | **Broken**: data written doesn't reach container's stdin |
| **Old approach** (exec + logs) | Logs demuxed by Docker, parsed with heuristic | `/proc/1/fd/0` via exec | Works (mostly) | Race condition + fragile log-parsing heuristic |

**Rationale:** The combined socket approach was the original design goal, but spike testing proved that writing to stdin via the attach socket doesn't deliver data to the container in this Docker setup. The hybrid approach achieves the same reliability goal (no race condition, no `time.sleep`) while keeping the proven write mechanism. The `/proc` dependency is retained only for the write path, which is less invasive than the original exec+logs approach's `/proc` + sleep combined fragility.

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
| `exec sh -c echo ... > /proc/1/fd/0` might fail (shell unavailable, `/proc` restricted, container terminated) | Medium | Request not delivered; response never arrives | Container-level timeout on socket read catches this; fallback to `container.logs()` as safety net |
| Socket close can race with container shutdown | Medium | ConnectionError propagated to consumer | `_send_shutdown` uses its own `attach_socket` call (stdin-only), which is unaffected. If the container dies mid-RPC, `readline()` returns empty string (EOF) → clean ConnectionError. |
| Entrypoint stdout has multiple frames (split across multiple TCP segments) | Low for small JSON responses, possible for large responses | Read might get partial JSON | Buffer all stdout frames until we have a complete JSON object. The `_DockerFrameReader` concatenates all payloads from stdout frames. |
| Performance: `container.exec_run` call per RPC adds overhead | Low (exec handshake is ~10ms locally) | Not noticeable for code execution (100ms+) | Acceptable. The attach socket read eliminates the dominant cost (the sleep) and the log-parsing heuristic. |

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

### Task 1.1b: `exec_run` write to `/proc/1/fd/0` — revised finding

**Earlier finding (incorrect):** Writing via `docker exec` → Python `open('/proc/1/fd/0', 'w')` fails with `OSError: [Errno 22] Invalid argument`. This was the original spike result.

**Revised finding (corrected by follow-up spike):** Writing via the Python `open()` approach fails, but writing via **shell redirection** — `docker exec sh -c echo '...' > /proc/1/fd/0` — works reliably. The shell's `echo` built-in opens PID 1's stdin file descriptor via the shell's own `/proc` access path, which avoids the OSError seen with a separate Python `open()` call.

**Action:** Use `docker exec sh -c echo '...' > /proc/1/fd/0` for writing the request to stdin (proven working), and use a stdout-only `attach_socket` for reading the response. The combined attach socket approach (stdin+stdout) was abandoned because writing to stdin via the attach socket doesn't deliver data to the container.