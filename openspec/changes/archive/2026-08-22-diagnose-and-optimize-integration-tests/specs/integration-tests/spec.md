## ADDED Requirements

### Requirement: Integration test performance is measurable

The integration test suite SHALL support runtime attribution so that each test's execution time can be broken down by phase: container startup, Docker API calls, JSON-RPC communication, assertion overhead, and cleanup.

#### Scenario: Test runtime can be attributed by phase
- **WHEN** a test runs through its lifecycle (setup, exercise, verify, teardown)
- **THEN** the time spent in container creation, RPC communication, assertion wait, and cleanup can be logged separately
- **AND** a profiling report can be generated showing cumulative and per-test phase times

### Requirement: Timeout tests do not rely on wall-clock waits

The integration test suite SHALL ensure that no test assertion waits for a real wall-clock timeout to expire. Timeout enforcement scenarios SHALL use deterministic signaling — such as a short controlled timeout value — to complete in under 1 second of actual wait time.

#### Scenario: Network isolation test completes immediately after network is disconnected
- **WHEN** a container's network is disconnected
- **AND** code attempts an outbound connection
- **THEN** the connection failure is detected within 1 second (not the default OS-level timeout of 5+ seconds)

#### Scenario: Execution timeout test completes promptly
- **WHEN** code is executed with a short timeout (e.g., 0.1 seconds)
- **AND** the code would take longer than the timeout
- **THEN** the timeout error is returned in under 2 seconds total test time

### Requirement: JSON-RPC communication uses event-driven synchronization

The `container_rpc()` method SHALL replace sleep-based polling (`time.sleep(0.3)`) with a mechanism that synchronizes on the container's response being ready — either via event-driven signaling (e.g., inotify, exit code detection) or a configurable short-poll with exponential backoff that completes within 50ms when the response is already present.

#### Scenario: RPC call completes immediately when response is ready
- **WHEN** a JSON-RPC request is sent to a responsive container
- **THEN** the response is returned within 100ms of the container writing it (not delayed by a fixed 300ms sleep)

#### Scenario: RPC call still succeeds under heavy container load
- **WHEN** a JSON-RPC request is sent to a busy container
- **THEN** the response is eventually returned (the synchronization degrades gracefully, not fails)

### Requirement: Containers may be reused across tests where isolation is not being tested

The integration test suite SHALL support sharing containers across multiple tests within a fixture scope (class or session) for tests that do not exercise session isolation. Tests that validate session-level concerns (e.g., independent sessions, session lifecycle) SHALL continue to use fresh containers per test.

#### Scenario: Code execution tests share a container within a test class
- **WHEN** tests in `TestCodeExecution` class run with a class-scoped container
- **THEN** all tests in that class execute against the same container
- **AND** state set by one test (e.g., `x = 42`) is visible to subsequent tests in the same class
- **AND** each test still runs its own assertion and verification independently

#### Scenario: Session lifecycle tests use fresh containers
- **WHEN** tests in `TestSessionCreate` or `TestSessionEnd` classes run
- **THEN** each test creates and destroys its own container
- **AND** the container lifecycle (create + end) is tested by each individual test

### Requirement: Integration test suite may run in parallel

The integration test suite SHALL support parallel test execution (via pytest-xdist) at the test-module or test-class granularity, with container names scoped to avoid name collisions.

#### Scenario: Two test files run concurrently without collision
- **WHEN** `test_integration_execution.py` and `test_integration_security.py` run in parallel
- **THEN** containers are named or labeled to avoid Docker name conflicts
- **AND** container cleanup picks up all created containers
- **AND** independent test assertions pass in both files