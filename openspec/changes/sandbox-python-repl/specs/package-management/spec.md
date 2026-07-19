## ADDED Requirements

### Requirement: Install packages via uv
The system SHALL install Python packages in a session using `uv pip install`, temporarily enabling network access for the container.

- `session_id`: target session
- `packages`: list of packages with optional version specifiers

#### Scenario: Install a package
- **WHEN** a client calls `install_packages(session_id="sess_abc", packages=[{"name": "pandas"}])`
- **THEN** the system connects the container's network, runs `uv pip install pandas`, disconnects the network
- **AND** the package is importable in subsequent `execute_python` calls

#### Scenario: Install specific version
- **WHEN** a client calls `install_packages(session_id="sess_abc", packages=[{"name": "pandas", "version": "2.0.0"}])`
- **THEN** the system installs `pandas==2.0.0`
- **AND** `import pandas; pandas.__version__` returns `"2.0.0"`

#### Scenario: Install multiple packages
- **WHEN** a client calls `install_packages(session_id="sess_abc", packages=[{"name": "numpy"}, {"name": "scipy", "version": "1.11.0"}])`
- **THEN** the system installs both packages in a single `uv pip install` invocation

### Requirement: Network isolation during installation
The system SHALL ensure network is only available to the container during `install_packages` calls. At all other times, including during `execute_python`, the container SHALL have no network access.

#### Scenario: Network removed after install
- **WHEN** `install_packages` completes successfully
- **THEN** the container's network SHALL be disconnected
- **AND** any subsequent `execute_python` code that attempts network access SHALL fail

#### Scenario: Network added before install
- **WHEN** `install_packages` is called on a session
- **THEN** the container's network SHALL be connected before the `uv pip install` command runs
- **AND** disconnected after the command completes

### Requirement: Package installation in custom venv
The system SHALL install packages into the session's dedicated virtual environment managed by `uv`.

#### Scenario: Packages installed in session venv
- **WHEN** packages are installed in a session
- **THEN** they SHALL be installed into `/session/venv/`
- **AND** the session's Python process SHALL have the venv activated (sys.path configured)

### Requirement: Package isolation between sessions
Packages installed in one session SHALL NOT affect other sessions, even if they use the same Python version.

#### Scenario: Packages are session-scoped
- **WHEN** `pandas` is installed in `session_abc`
- **AND** no packages are installed in `session_def`
- **THEN** `import pandas` succeeds in `session_abc`
- **AND** `import pandas` fails in `session_def`