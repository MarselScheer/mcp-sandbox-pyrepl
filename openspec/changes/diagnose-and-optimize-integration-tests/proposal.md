## Why

The project's ~20 integration tests take significantly longer to run than the ~80 unit tests, making the `make test-integration` feedback loop impractical for frequent use. The root causes are unconfirmed — they may be a combination of per-test container startup overhead, synchronous sleep-based waits in the JSON-RPC communication layer, and slow-to-timeout test assertions. Before optimizing, we must measure where the time goes; then fix the most impactful bottlenecks.

## What Changes

- Profile the integration test suite to attribute runtime to specific phases (container startup, RPC calls, test assertions, cleanup).
- Fix the `container_rpc()` method's `time.sleep(0.3)` polling — replace it with an event-driven synchronization, or at minimum a configurable/adjustable short poll.
- Fix slow test assertions that wait on real wall-clock timeouts instead of using deterministic signals (e.g., a `urllib.request.urlopen(timeout=5)` in the network isolation test, and a `timeout 5` CLI command in the execution timeout test).
- Optimize per-test container startup overhead — introduce container reuse strategies (class-scoped or session-scoped containers where isolation permits, or parallel test execution via pytest-xdist).
- Name this change: **diagnose-and-optimize-integration-tests**.

## Capabilities

### Modified Capabilities
- `integration-tests`: Add requirements for performance benchmarking (test attribution by phase), timeout-responsive assertions (non-wall-clock), and session-scoped container reuse strategy with documented isolation guarantees.

## Impact

- `tests/conftest.py`: Fixture reorganization (session/class-scoped images, containers, data dirs).
- `tests/rpc_helpers.py` / `src/docker_adapter.py`: The `container_rpc` method's polling mechanism needs a non-sleep-based synchronization.
- Test files: Individual tests change to use shared containers where isolation is not being tested, and assertion timeouts become immediate.
- `pyproject.toml`: May add `pytest-xdist` dependency for parallel execution.
- Integration test run time should drop from O(minutes) to O(seconds).