# Integration Tests

## Purpose

End-to-end test suite that validates the full stack (MCP tools → SessionManager → Docker containers → entrypoint JSON-RPC server) against real Docker containers. Covers session lifecycle, code execution, package installation, file I/O, timeout enforcement, and session isolation.

## Requirements

### Requirement: Integration test for session lifecycle
The integration test suite SHALL validate that sessions can be created, listed, inspected, and terminated using real Docker containers.

#### Scenario: Create and end a session with default Python version
- **WHEN** a `SessionManager` creates a session with `python_version="3.12"`
- **THEN** the container starts successfully
- **AND** `list_sessions()` returns the session in the active list
- **AND** `get_session()` returns the session metadata
- **AND** after `end_session()`, the container is stopped and removed
- **AND** `list_sessions()` no longer includes the ended session

#### Scenario: Create session with custom image
- **WHEN** a `SessionManager` creates a session with `image="sandbox-base:3.12"`
- **THEN** the container starts from the specified image
- **AND** the session is operational (can execute code)

#### Scenario: End session is idempotent
- **WHEN** a `SessionManager` calls `end_session()` on a session that has already been ended
- **THEN** the call returns success without error

### Requirement: Integration test for code execution
The integration test suite SHALL validate that Python code can be executed in a sandboxed container and results returned correctly.

#### Scenario: Execute code and capture stdout
- **WHEN** a `SessionManager` executes code `print("hello from docker")` in a session
- **THEN** the result contains `stdout` with `"hello from docker"`

#### Scenario: Execute code and capture display output
- **WHEN** a `SessionManager` executes code `[1, 2, 3]` (expression producing a value) in a session
- **THEN** the result contains `display` with `["[1, 2, 3]"]`

#### Scenario: State persists across executions
- **WHEN** a `SessionManager` executes code `x = 42` in a session
- **AND** then executes `print(x)` in the same session
- **THEN** the second result contains `stdout` with `"42"`

#### Scenario: Syntax error is reported
- **WHEN** a `SessionManager` executes code with a syntax error in a session
- **THEN** the result contains an `error` field with `SyntaxError`

#### Scenario: Runtime error is reported
- **WHEN** a `SessionManager` executes code `1/0` in a session
- **THEN** the result contains an `error` field with `ZeroDivisionError`

#### Scenario: Execution timeout is enforced
- **WHEN** a `SessionManager` executes code `import time; time.sleep(60)` with `timeout=5` in a session
- **THEN** the result indicates a timeout error within approximately 5 seconds

#### Scenario: Namespace reset clears state
- **WHEN** a `SessionManager` executes code `x = 42` in a session
- **AND** then executes code with `reset=True`
- **AND** then executes `print(x)`
- **THEN** the third execution returns an error indicating `x` is not defined

### Requirement: Integration test for package installation
The integration test suite SHALL validate that packages can be installed via `uv pip install` and used in subsequent code execution.

#### Scenario: Install and use a package
- **WHEN** a `SessionManager` installs a package (e.g., `"pytz"`) in a session with network connected
- **AND** then executes code `import pytz; print(pytz.__version__)`
- **THEN** the execution succeeds and prints the installed version

#### Scenario: Package isolation between sessions
- **WHEN** a `SessionManager` installs package `"pytz"` in session A
- **AND** session B was created without the package
- **THEN** executing `import pytz` in session B fails with `ModuleNotFoundError`

### Requirement: Integration test for file I/O
The integration test suite SHALL validate that files can be written to and read from the session's data volume, and that files written by the host are visible inside the container.

#### Scenario: Host writes file, container reads it
- **WHEN** a `SessionManager` writes file content to a session's data volume via the MCP tool
- **AND** the container executes code to read the file from `/data/<path>`
- **THEN** the file content is correctly read inside the container

#### Scenario: Container writes file, host reads it
- **WHEN** a `SessionManager` executes code that writes a file to `/data/output.csv` inside the container
- **AND** the host reads the file from the session's data volume
- **THEN** the file content matches what the container wrote

### Requirement: Integration test for security constraints
The integration test suite SHALL validate that security constraints are enforced on real Docker containers.

#### Scenario: Container runs as non-root user
- **WHEN** a `SessionManager` executes code `import os; print(os.getuid())` in a session
- **THEN** the output is `"1000"` (the sandbox user UID)

#### Scenario: Cannot write outside /data
- **WHEN** a `SessionManager` executes code `open("/tmp/test.txt", "w")` in a session
- **THEN** the execution returns a permission error

#### Scenario: No network during code execution
- **WHEN** a `SessionManager` executes code `import urllib.request; urllib.request.urlopen('http://example.com')` in a session
- **THEN** the execution returns a network error (DNS resolution failure or connection timeout)

### Requirement: Integration test for session isolation
The integration test suite SHALL validate that multiple sessions are isolated from each other — separate namespaces, separate containers, no cross-session interference.

#### Scenario: Independent namespaces
- **WHEN** a `SessionManager` executes code `x = 42` in session A
- **AND** executes code `print(x)` in session B
- **THEN** session B's execution returns an error indicating `x` is not defined

#### Scenario: Independent containers
- **WHEN** session A and session B are created
- **THEN** they run in separate Docker containers
- **AND** ending session A does not affect session B

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