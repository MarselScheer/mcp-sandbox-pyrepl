## Context

`container_rpc()` currently writes via `docker exec ["python3", "-c", "..."]` writing to `/proc/1/fd/0` and reads via `container.logs(stdout=True, stderr=False, tail=5)` with exponential backoff. The spike proved that a single `attach_socket()` call gives us a raw bidirectional socket — we can `sendall()` the request and parse Docker's multiplexed frames from the read side, eliminating both the subprocess and the polling loop.

The `container_stdin()` method already has the `SocketIO` unwrapping logic. This design extracts that into a shared helper and builds the new `container_rpc()` on top of it.

## Goals / Non-Goals

**Goals:**
- Replace `docker exec` subprocess with raw socket `sendall()`
- Replace `container.logs()` + polling loop with blocking `recv()` on the attach socket
- Extract a shared `_attach_raw_socket()` helper used by both `container_stdin()` and `container_rpc()`
- Maintain identical JSON-RPC semantics (protocol, error handling, response format, timeout behavior)

**Non-Goals:**
- No changes to `DockerClient` Protocol or `SessionManager` — the refactoring is entirely inside `RealDockerClient`
- No changes to the entrypoint's behavior or output format
- No changes to `container_stdin()`'s public API — only internal refactoring to use the shared helper

## Decisions

### Decision 1: `_attach_raw_socket(params)` — shared helper

Extract the socket unwrapping into a private helper with explicit `params` for the `attach_socket()` call. `container_stdin()` calls it with `{"stdin": 1, "stream": 1, "logs": 1}` (stdin-only). `container_rpc()` calls it with `{"stdin": 1, "stdout": 1, "stderr": 1, "stream": 1, "logs": 1}` (bidirectional).

```python
def _attach_raw_socket(self, container_id: str, params: dict[str, int]) -> socket.socket:
    container = self.container_get(container_id)
    sock = container.attach_socket(params=params)
    if isinstance(sock, socket.socket):
        return sock
    if hasattr(sock, "_sock") and isinstance(sock._sock, socket.socket):
        return sock._sock
    raise TypeError(f"Unexpected attach_socket type: {type(sock)}")
```

**Alternative considered:** Keep the unwrapping duplicated in both methods. Rejected — the `SocketIO` unwrapping pattern is non-obvious; a single helper avoids drift.

### Decision 2: Read-side uses explicit frame parsing

Docker multiplexes stdout/stderr over the attached socket using an 8-byte frame header:

```
Byte  0     : stream type  (1=stdout, 2=stderr)
Bytes 1-3   : reserved (zero)
Bytes 4-7   : payload length (big-endian uint32)
Bytes 8..N  : payload bytes
```

A `_recv_exact()` helper reads exactly N bytes (handles partial `recv()` returns). `_read_frame()` reads one header + payload, returning `(stream_type, payload)` or `None` on EOF.

**Alternative considered:** Use `sock.makefile("r")` and read lines. Rejected — the frame header bytes would appear as garbage in the text stream, and `makefile()` on a non-seekable socket is fragile.

### Decision 3: Socket timeout replaces polling loop

```python
sock.settimeout(timeout)
try:
    while True:
        frame = self._read_frame(sock)
        if frame is None:
            raise ConnectionError("Connection closed before response received")
        stream_type, payload = frame
        if stream_type != 1:  # skip stderr frames
            continue
        # parse JSON, match by request id
except socket.timeout:
    raise ConnectionError(f"No response within {timeout}s")
```

The current polling loop uses exponential backoff from 10ms to 100ms, yielding ~100 reads per second max. The socket approach blocks until data arrives or the timeout fires — zero wasted CPU.

### Decision 4: Shared `_rpc_counter` and `request["id"]` matching preserved

The same `_rpc_counter` and `request["id"]` matching strategy is kept. Each call increments `_rpc_counter`, writes `{"id": counter, ...}`, and reads frames looking for `{"id": counter, ...}`. Since calls are synchronous (one RPC at a time, no concurrency on the socket), this is defensive against stale responses from previous calls.

### Decision 5: Stderr frames logged but not returned

If the entrypoint writes to stderr (unexpected tracebacks, debug output), those frames are type 2 and are silently discarded. A `logging.debug()` call could be added for diagnostics.

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| **SocketIO on Python 3.14+** — `attach_socket()` returns a read-only `SocketIO` instead of a writable `socket.socket` | The `_attach_raw_socket()` helper unwraps via `._sock`, already proven in the `container_stdin()` fix and spike |
| **Partial `recv()`** — TCP can split frames across boundaries | `_recv_exact()` loops until all N bytes collected, handles EOF gracefully |
| **Stale JSON from previous RPC cycle** — logs buffer might have leftover output | Matching by `request["id"]` handles this, same as current implementation |
| **Header format changes in future Docker versions** | 8-byte header with `b'\x00\x00\x00'` at bytes 1-3 is a stable Docker API — if it changes, we'll see a struct unpack error and can adapt |
| **Concurrent `container_rpc()` on same container** — currently not supported, but unsynchronized | The current implementation already lacks concurrency support (same `_rpc_counter`). Document that callers must serialize RPC calls per container |