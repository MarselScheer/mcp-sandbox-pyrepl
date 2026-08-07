# Session Lifecycle

## Purpose

Manages the full lifecycle of sandboxed REPL sessions backed by Docker
containers. Supports creating sessions with configurable Python versions,
custom images, and pre-installed packages; listing active sessions; retrieving
session details; and cleanly terminating sessions.

## Requirements

### Requirement: Create session
The system SHALL create a new sandboxed REPL session backed by a Docker container.

- `session_id`: unique identifier (e.g., `sess_<random>`)
- `python_version`: MUST select the corresponding Docker image from the image registry
- `image`: optional override to use a custom Docker image
- `packages`: optional list of packages to pre-install via `uv` after container start

#### Scenario: Create session with default Python version
- **WHEN** a client calls `create_session(python_version="3.12")`
- **THEN** the system starts a Docker container from `sandbox-base:3.12` with the sandbox security profile
- **AND** returns a unique `session_id`

#### Scenario: Create session with pre-installed packages
- **WHEN** a client calls `create_session(python_version="3.12", packages=["pandas", "numpy"])`
- **THEN** the system starts the container, connects network, installs both packages via `uv`, disconnects network
- **AND** returns a `session_id`

#### Scenario: Create session with custom image
- **WHEN** a client calls `create_session(image="my-data-sandbox:latest")`
- **THEN** the system starts a container from the specified custom image
- **AND** the custom image's pre-installed packages are available in the session

#### Scenario: Create session with invalid Python version
- **WHEN** a client calls `create_session(python_version="2.7")`
- **THEN** the system returns an error indicating the version is not available

### Requirement: List sessions
The system SHALL provide a list of all active sessions with their metadata.

#### Scenario: List active sessions
- **WHEN** a client calls `list_sessions()`
- **THEN** the system returns a list of active `session_id` values with their Python version, image, creation time, and status

### Requirement: Get session info
The system SHALL provide detailed information about a specific session.

#### Scenario: Get session details
- **WHEN** a client calls `get_session(session_id="sess_abc")`
- **THEN** the system returns the session's Python version, image, creation time, status, and uptime

### Requirement: End session
The system SHALL cleanly terminate a session, stopping and removing the Docker container.

#### Scenario: End active session
- **WHEN** a client calls `end_session(session_id="sess_abc")`
- **THEN** the system sends a `shutdown` JSON-RPC request to the container
- **AND** stops and removes the Docker container
- **AND** cleans up the session's `/data` directory
- **AND** returns success

#### Scenario: End already-ended session
- **WHEN** a client calls `end_session(session_id="sess_abc")`
- **AND** the session has already been ended or never existed
- **THEN** the system returns success (idempotent)

### Requirement: Session recovery on timeout
When a session's container is restarted due to a timeout, the system SHALL transparently handle recovery.

#### Scenario: Recover session after timeout
- **WHEN** a client calls `execute_python(session_id="sess_abc", code="...")`
- **AND** the previous execution caused a timeout and container restart
- **THEN** the system restarts the container silently
- **AND** returns the execution result with a `session_reset` flag indicating the namespace was lost