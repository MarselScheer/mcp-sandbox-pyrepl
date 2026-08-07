# Sandbox Security

## Purpose

Defines the security constraints for sandboxed REPL containers. Enforces
non-root execution, read-only root filesystem, dropped Linux capabilities,
network isolation during code execution, and no host access — ensuring tenant
isolation and system integrity.

## Requirements

### Requirement: Non-root user inside container
The REPL process inside the container SHALL run as a non-root user (`sandbox`, UID 1000).

#### Scenario: Process runs as non-root
- **WHEN** a session container starts
- **THEN** the REPL entrypoint process SHALL run as user `sandbox` (UID 1000)
- **AND** the process SHALL NOT have root privileges

### Requirement: Read-only root filesystem
The container's root filesystem SHALL be mounted as read-only. Only the `/data` and `/session` directories SHALL be writable.

#### Scenario: Cannot write outside /data and /session
- **WHEN** code inside the container attempts to write to `/tmp/foo.txt`
- **THEN** the write SHALL fail with a permission error

#### Scenario: Can write to /data
- **WHEN** code inside the container writes to `/data/output.csv`
- **THEN** the write SHALL succeed

#### Scenario: Can write to /session
- **WHEN** the REPL entrypoint writes to `/session/history.sqlite`
- **THEN** the write SHALL succeed

### Requirement: All Linux capabilities dropped
The container SHALL be started with `--cap-drop ALL`, removing all Linux capabilities.

#### Scenario: No elevated capabilities
- **WHEN** code inside the container attempts to use privileged operations (e.g., `mount`, `ptrace`, `setuid`)
- **THEN** the operations SHALL fail with permission errors

### Requirement: Network isolation during code execution
The container SHALL have no network access during `execute_python` calls. Network SHALL only be connected during `install_packages` calls.

#### Scenario: No network during code execution
- **WHEN** a client calls `execute_python(session_id="sess_abc", code="import urllib.request; urllib.request.urlopen('http://example.com')")`
- **THEN** the request SHALL fail with a network error

#### Scenario: Network available during install
- **WHEN** a client calls `install_packages(session_id="sess_abc", packages=[{"name": "pandas"}])`
- **THEN** the container SHALL have network access during the `uv pip install` invocation

### Requirement: No host access
The container SHALL NOT have access to the host's Docker socket, processes, or filesystem (except the mounted `/data` volume).

#### Scenario: Cannot access Docker socket
- **WHEN** code inside the container attempts to access `/var/run/docker.sock`
- **THEN** the access SHALL fail (the socket is not mounted)