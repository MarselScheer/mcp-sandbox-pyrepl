# Code Execution

## Purpose

Provides sandboxed Python code execution within a session's persistent
namespace. Supports execution with configurable timeouts, comprehensive error
reporting (syntax and runtime), display hook capture, help output, and
namespace reset without container restart.

## Requirements

### Requirement: Execute Python code
The system SHALL execute arbitrary Python code in a session's persistent namespace, returning stdout, stderr, display output, and errors.

- `session_id`: target session
- `code`: string of Python code to execute
- `timeout`: optional max execution time in seconds (default: 30)

#### Scenario: Execute simple expression
- **WHEN** a client calls `execute_python(session_id="sess_abc", code="2 + 2")`
- **THEN** the system returns `{stdout: "", stderr: "", display: ["4"]}`

#### Scenario: Execute code with print output
- **WHEN** a client calls `execute_python(session_id="sess_abc", code="print('hello world')")`
- **THEN** the system returns `{stdout: "hello world\n", stderr: "", display: []}`

#### Scenario: State persists across calls
- **WHEN** a client calls `execute_python(session_id="sess_abc", code="x = 42")`
- **THEN** a subsequent call `execute_python(session_id="sess_abc", code="print(x)")`
- **THEN** returns `{stdout: "42\n"}`

### Requirement: Execution timeout
The system SHALL enforce a configurable timeout on code execution. If the timeout is exceeded, the thread SHALL be interrupted. If the thread cannot be interrupted, the session SHALL be marked as corrupted and the container restarted.

#### Scenario: Execution times out
- **WHEN** a client calls `execute_python(session_id="sess_abc", code="import time; time.sleep(60)", timeout=5)`
- **THEN** the system returns an error after 5 seconds indicating the execution timed out

#### Scenario: Session recovers after hard timeout
- **WHEN** a previous execution caused a hard timeout (thread unsalvageable)
- **AND** the client calls `execute_python(session_id="sess_abc", code="print('recovered')")`
- **THEN** the system restarts the container and returns the result with a `session_reset` flag

### Requirement: Syntax error reporting
The system SHALL return syntax errors with file, line number, and error message.

#### Scenario: Syntax error in code
- **WHEN** a client calls `execute_python(session_id="sess_abc", code="x = "))`
- **THEN** the system returns `{error: "SyntaxError: invalid syntax (line 1)"}`

### Requirement: Runtime error reporting
The system SHALL return runtime errors with traceback information.

#### Scenario: Runtime error
- **WHEN** a client calls `execute_python(session_id="sess_abc", code="1/0")`
- **THEN** the system returns `{error: "ZeroDivisionError: division by zero"}` with traceback in stderr

### Requirement: Display hook output
The system SHALL capture the Python REPL display hook (evaluated expressions that produce a value) and return them as a `display` list.

#### Scenario: Last expression output
- **WHEN** a client calls `execute_python(session_id="sess_abc", code="[1, 2, 3]")`
- **THEN** the system returns `{display: ["[1, 2, 3]"]}`

### Requirement: Help output
The system SHALL return `help()` output as part of stdout.

#### Scenario: Help on a function
- **WHEN** a client calls `execute_python(session_id="sess_abc", code="import pandas; help(pandas.DataFrame.describe)")`
- **THEN** the system returns the help text in `stdout`

### Requirement: Reset namespace
The system SHALL support resetting the session's namespace to a clean state without restarting the container.

#### Scenario: Reset session
- **WHEN** a client calls `execute_python(session_id="sess_abc", code="x = 42")`
- **AND** then calls `execute_python(session_id="sess_abc", reset=True)`
- **AND** then calls `execute_python(session_id="sess_abc", code="print(x)")`
- **THEN** the third call returns a `NameError` because `x` is no longer defined