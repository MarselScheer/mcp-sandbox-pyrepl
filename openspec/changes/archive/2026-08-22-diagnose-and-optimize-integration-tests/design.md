## Context

The current integration test suite (see `proposal.md` for motivation) creates a fresh Docker container per test via a function-scoped `session` fixture. Each container startup takes ~1-2 seconds. With ~20 tests that's 20-40 seconds of container lifecycle overhead alone.

Additionally, the JSON-RPC communication path in `RealDockerClient.container_rpc()` (in `src/docker_adapter.py`) uses a fixed `time.sleep(0.3)` to wait for the container's response — a known race condition documented by a `TODO` comment in the code. Each RPC call adds 300ms of dead time. Tests making 3-4 RPC calls accumulate 900-1200ms.

Two test assertions use real wall-clock timeouts:
- `test_network_isolation_during_execution` uses `urllib.request.urlopen('http://example.com', timeout=5)` — the OS-level TCP timeout takes ~5 seconds.
- `test_execution_timeout_enforced` uses the Linux `timeout 5` CLI command — the `timeout` command waits 5 seconds.

## Goals / Non-Goals

**Goals:**
- Profile integration test runtime by phase (container startup, RPC, assertions, cleanup) to identify the actual bottlenecks.
- Replace `container_rpc()`'s fixed 300ms sleep with a mechanism that completes within 50ms when the response is already present.
- Fix the network isolation test to detect disconnection in under 1 second instead of waiting 5 seconds for OS-level TCP timeout.
- Fix the execution timeout test to complete promptly using the entrypoint's own timeout mechanism rather than the OS `timeout` command.
- Reuse containers across tests in the same class where session isolation is not the subject under test, reducing per-test container startup overhead.
- Support parallel test execution at the module or class level via pytest-xdist.

**Non-Goals:**
- Replacing the JSON-RPC communication protocol itself — only the polling/synchronization mechanism inside `container_rpc()` changes.
- Changing the session lifecycle, isolation, or security test design — those must continue to use fresh containers.
- CI integration — that's a separate, already archived concern.
- Replacing the existing conftest.py fixture architecture entirely — only extending it with scoped variants.

## Decisions

### Decision 1: Profile before optimizing — use pytest --durations and manual timing hooks

Instead of guessing which phase is slowest, first measure. Use `pytest --durations=0` (show all test times) plus custom timing fixtures that log per-phase durations (container_create, container_rpc, assertions, end_session). This produces a concrete attribution table.

**Alternatives considered:**
- pytest-profiling / pytest-benchmark plugins: Rich but add a dependency. Since we only need attribution, not statistical benchmarking, simple `time.perf_counter()` logging at fixture boundaries is sufficient and zero-dependency.
- cProfile / py-spy: Process-level profiling captures internal function times but not conceptual phases like "container creation". We need phase-level, not function-level.

### Decision 2: Replace `time.sleep(0.3)` with a short-poll + backoff in `container_rpc()`

The current approach is a fixed 300ms sleep before reading logs. Replace it with a polling loop that reads `container.logs()` in a tight loop (10ms per iteration, exponential backoff to 100ms max, timeout at 5s). When the response is already present (fast container), the first iteration reads it within the 10ms sleep — a 30x improvement over 300ms. Under load, the backoff ensures we don't busy-spin.

```python
# Before
time.sleep(0.3)
logs = container.logs(stdout=True, stderr=False, tail=5).decode("utf-8")

# After
import time
backoff = 0.01  # 10ms initial
max_backoff = 0.1  # 100ms max
total_wait = 0.0
timeout = 5.0
while total_wait < timeout:
    logs = container.logs(stdout=True, stderr=False, tail=5).decode("utf-8")
    for line in reversed(logs.strip().split("\n")):
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    time.sleep(backoff)
    total_wait += backoff
    backoff = min(backoff * 1.5, max_backoff)
raise ConnectionError(...)
```

**Alternatives considered:**
- inotify on `/proc/1/fd/1` (container PID 1 stdout): Requires the container process to cooperate with filesystem signaling. The entrypoint writes to stdout inside the container, not to a file. inotify would not trigger on pipe writes.
- `docker exec cat /proc/1/fd/1`: Would read partial data and is fragile.
- attach_socket with proper 8-byte frame header parsing: More robust long-term but a larger refactor. The short-poll approach is a minimal-risk improvement within the existing architecture.

### Decision 3: Reuse containers via class-scoped `session_manager` and `session` fixtures

Introduce a `class_container` fixture that creates a single container per test class (not per test function). Tests that need container isolation keep the existing function-scoped `session` fixture. Tests that only need a container to execute code against use the class-scoped fixture.

```python
@pytest.fixture(scope="class")
def class_session(session_manager: SessionManager) -> Generator[str, None, None]:
    session_id = session_manager.create_session(python_version="3.12")
    yield session_id
    session_manager.end_session(session_id)
```

Tests in `TestCodeExecution`, `TestFileIO`, and `TestPackageInstallation` can all share this class-scoped container. `TestSessionCreate`, `TestSessionEnd`, `TestSessionList`, and `TestSecurityConstraints` must keep function-scoped sessions because they test session lifecycle and isolation.

This reduces container startups from ~20 to ~10 (accounting for non-reusable tests still needing fresh containers).

**Alternatives considered:**
- Session-scoped containers (single container for all tests): Too risky — a single corrupted session from one test would cascade to all subsequent tests.
- Pre-created container pool (docker-compose with multiple containers): Over-engineered for ~20 tests.
- pytest-xdist parallelization alone: Complements container reuse but doesn't fix per-test startup overhead. Both strategies together multiply the benefit.

### Decision 4: Fix network isolation test with immediate socket probe

Replace `urllib.request.urlopen('http://example.com', timeout=5)` with a short-lived TCP socket connection attempt using socket module with a 0.5s timeout — fast enough to fail immediately after network disconnect, since the kernel TCP handshake gets an ICMP unreachable from the disconnected interface.

```python
# Before
result = container.exec_run([
    "python3", "-c",
    "import urllib.request; urllib.request.urlopen('http://example.com', timeout=5)"
])

# After
result = container.exec_run([
    "python3", "-c",
    "import socket; s = socket.socket(); s.settimeout(0.5); s.connect(('example.com', 80))"
])
```

The socket `connect()` with short timeout fails immediately (~100ms) when the network is disconnected because the kernel returns `EHOSTUNREACH` or `ENETUNREACH` — no 5-second TCP SYN retry needed.

**Alternatives considered:**
- `--timeout=0.1` on urllib: Already using `timeout=5`. Lowering to 0.1 reduces wall-clock wait but still waits for the TCP SYN to time out. A raw socket with short timeout is more explicit and reliable.
- `ping -c 1 -W 1 example.com`: Uses ping instead of HTTP, same ~1s timeout issue.

### Decision 5: Fix execution timeout test through the entrypoint's own timeout mechanism

Replace the OS-level `timeout 5` wrapper with the entrypoint's own timeout parameter. The entrypoint (via `ThreadTimeoutStrategy`) already supports configurable timeouts through the JSON-RPC `exec` method's `params.timeout` field. Sending an `exec` request with `timeout=0.1` exercises the real timeout enforcement path and completes in ~100ms instead of 5 seconds.

```python
# Before
result = container.exec_run(["timeout", "5", "python3", "-c", "import time; time.sleep(60)"])

# After
response = rpc_call(docker_client, container_id, {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "exec",
    "params": {"code": "import time; time.sleep(60)", "timeout": 0.1},
})
```

This tests the production timeout enforcement path (ThreadTimeoutStrategy) rather than the OS `timeout` command — a more realistic test in addition to being faster.

**Alternatives considered:**
- Keep `timeout 5` but reduce to `timeout 0.5`: Still an OS-level timeout, not testing the actual timeout stack. The entrypoint's timeout mechanism is what production code uses. Testing it directly is both faster and more relevant.
- Remove the test entirely: The timeout test exercises an important failure mode and should stay, just use the right mechanism.

## Risks / Trade-offs

- **[Risk] Polling in `container_rpc()` still has race window**: The short-poll backoff is probabilistic, not event-driven. If logs are flushed between iterations, the next iteration catches it within 10ms. Mitigation: The window is small enough that flaky failures would be extremely rare. If they occur, switch to attach_socket with frame parsing.
- **[Risk] Class-scoped containers leak state between tests**: A test could set a variable that affects subsequent tests in the same class. Mitigation: Only share containers for tests that don't depend on specific session state. Tests that need isolated state (e.g., `test_state_persistence_via_data_volume`) can isolate within the test using `/data` or reset the namespace. Tests that explicitly test namespace behavior (like `test_namespace_reset_clears_session_state`) keep function-scoped containers.
- **[Risk] pytest-xdist container name collisions**: Parallel workers need unique container names. Mitigation: Session IDs already contain UUIDs (e.g., `sess_abc123...`), so collisions are astronomically unlikely. If issues arise, add a `process_id` to the session ID.
- **[Risk] Short socket timeout is fragile on slow CI runners**: 0.5-second socket timeout might be too aggressive on overloaded CI. Mitigation: Bump to 1.0s if flaky, or make configurable.
- **[Risk] Container reuse could mask interaction bugs that only appear with fresh containers**: E.g., volume initialization, entrypoint startup sequence. Mitigation: Class-scoped containers are limited to execution tests. Session lifecycle tests always use fresh containers. The existing unit test suite has extensive FakeDockerClient tests that cover edge cases without real containers.