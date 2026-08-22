## 1. Profile Integration Test Performance

- [x] 1.1 Add `--durations=0` to the `test-integration` Makefile target and run to capture baseline per-test times
- [x] 1.2 Add timing instrumentation to `tests/conftest.py`: wrap `session_manager` and `session` fixtures with `time.perf_counter()` logging at fixture setup/teardown boundaries (container_create, end_session)
- [x] 1.3 Add timing instrumentation to `container_rpc()` in `src/docker_adapter.py` to log per-RPC-call wall-clock time
- [x] 1.4 Run `make test-integration` and produce an annotated breakdown: total time, container startup sum, RPC call sum, teardown sum, slowest 3 tests, and candidate fix priorities

## 2. Fix `container_rpc()` Sleep-Based Polling

- [x] 2.1 Replace `time.sleep(0.3)` in `RealDockerClient.container_rpc()` with the short-poll + exponential backoff loop: 10ms initial, 100ms max backoff, 5s total timeout, reading `container.logs()` each iteration
- [x] 2.2 Update the `time.sleep(0.3)` usage in `src/docker_adapter.py` import list if `time` needs to remain imported (it's already used)
- [x] 2.3 Run `make test-integration` and verify all integration tests still pass with the new polling mechanism
- [x] 2.4 Remove the `TODO` comment about sleep-based polling being a race condition — the new polling mechanism addresses it

## 3. Fix Wall-Clock Timeout in Network Isolation Test

- [x] 3.1 In `tests/test_integration_security.py`, replace `urllib.request.urlopen('http://example.com', timeout=5)` with `socket.socket(); socket.settimeout(0.5); socket.connect(('example.com', 80))` that fails immediately on disconnected network
- [x] 3.2 Update the assertion keywords to match `socket` error messages (`connection refused`, `no route to host`, `timed out`) instead of `urllib`-specific messages
- [x] 3.3 Run `make test-integration` and verify the network isolation test completes in under 2 seconds

## 4. Fix Wall-Clock Timeout in Execution Timeout Test

- [x] 4.1 In `tests/test_integration_execution.py`, replace the `timeout 5 python3 -c "import time; time.sleep(60)"` command with a JSON-RPC `exec` call through `rpc_call()` using `timeout=1.0` (exercising the real `ThreadTimeoutStrategy`)
- [x] 4.2 Adjust the `elapsed` assertion — with `timeout=1.0` the test should complete within ~10 seconds total (accounting for entrypoint's 5s hard_timeout for thread cleanup)
- [x] 4.3 Run `make test-integration` and verify the execution timeout test completes in under 10 seconds for the RPC phase

## 5. Add Class-Scoped Container Fixture for Container Reuse

- [x] 5.1 Add a `class_container` fixture to `tests/conftest.py` (scope=`"class"`) that creates one container per test class and tears it down after the last test in the class
- [x] 5.2 Refactor `tests/test_integration_execution.py` `TestCodeExecution` class: request `class_container` instead of creating per-test sessions; keep `test_display_hook_*` and `test_namespace_reset_*` on class-scoped container (they use RPC, not session lifecycle)
- [x] 5.3 Refactor `tests/test_integration_files.py` `TestFileIO` class: request `class_container` instead of creating per-test sessions
- [x] 5.4 Refactor `tests/test_integration_packages.py` `TestPackageInstallation` class: request `class_container` for tests that share a container; keep `test_package_isolation_between_sessions` using the function-scoped `session_manager` fixture
- [x] 5.5 Run `make test-integration` and verify all tests pass with shared containers
- [x] 5.6 Run `make test-integration` and verify total runtime dropped compared to the baseline from profiling (step 1)

## 6. Support Parallel Test Execution

- [x] 6.1 Add `pytest-xdist` to the `dev` dependency group in `pyproject.toml`
- [x] 6.2 Add a `test-integration-parallel` Makefile target: `pytest -m integration -v --tb=short -n auto`
- [x] 6.3 Run `make test-integration-parallel` and verify no container name collisions or cross-test interference
- [x] 6.4 Document the parallel execution capability in the Makefile comment header

## 7. Validation

- [x] 7.1 Run `make test-integration` and verify all integration tests pass (timing assertions updated for new speed)
- [x] 7.2 Run `make test` (which runs unit tests) and verify no regressions
- [x] 7.3 Run `make test-integration-parallel` and verify it completes faster than the serial run
- [x] 7.4 Document the improvement: report before/after times in the Makefile's `test-integration` target description, or add a comment showing expected runtime