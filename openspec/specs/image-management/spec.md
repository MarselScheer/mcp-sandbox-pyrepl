# Image Management

## Purpose

Manages Docker images used for sandboxed REPL sessions. Provides a configurable
image registry mapping Python versions to Docker images, a base Dockerfile for
the `sandbox-base` image, support for custom images, and tooling to list
available images.

## Requirements

### Requirement: Image registry configuration
The system SHALL maintain a configurable mapping of Python version strings to Docker image names, stored in `config.yaml`.

#### Scenario: Default image mapping
- **WHEN** the system starts
- **THEN** it SHALL load the image registry from `config.yaml`
- **AND** make the following default mappings available: `3.9`, `3.10`, `3.11`, `3.12`, `3.13`

#### Scenario: Custom image mapping
- **WHEN** a user adds `"my-ds": "my-data-sandbox:latest"` to `config.yaml`
- **AND** the system is restarted
- **THEN** `create_session(image="my-ds")` SHALL use the custom image

### Requirement: Base image Dockerfile
The system SHALL provide a base Docker image (`sandbox-base`) with:
- Python 3.x installed
- `uv` installed
- The REPL entrypoint script
- A non-root `sandbox` user (UID 1000)

#### Scenario: Base image builds
- **WHEN** a user runs `docker build -t sandbox-base:3.12 images/sandbox-base/`
- **THEN** the image SHALL contain Python 3.12, `uv`, and the REPL entrypoint

### Requirement: Custom image support
Users SHALL be able to extend `sandbox-base` with their own Dockerfile to pre-install packages and tools.

#### Scenario: Custom image with pre-installed packages
- **WHEN** a user creates a Dockerfile:
  ```dockerfile
  FROM sandbox-base:3.12
  RUN uv pip install numpy pandas scikit-learn
  ```
- **AND** builds it as `my-sandbox:latest`
- **AND** configures the image in `config.yaml`
- **THEN** `create_session(image="my-sandbox")` SHALL make those packages available without network installation

### Requirement: List available images
The system SHALL provide a tool to list all available Python versions and custom images.

#### Scenario: List available images
- **WHEN** a client calls `list_python_versions()`
- **THEN** the system returns the list of configured Python versions and custom image aliases