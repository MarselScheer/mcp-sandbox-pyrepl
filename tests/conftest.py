"""Shared fixtures for integration tests.

Integration tests exercise the real Docker stack (SessionManager + Docker SDK).
Fixtures are organized with session-scoped caching (Docker availability check)
and function-scoped isolation (session, session manager).

Design:
- SessionManager gets a RealDockerClient adapter wrapping the docker-py SDK.
- All fixtures are self-skipping when Docker is unavailable.
- Cleanup is guaranteed via pytest fixture finalization.
- The sandbox image (``sandbox-base:3.12``) must be prebuilt via ``make build-image``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from docker_adapter import RealDockerClient
from session_manager import (
    SessionManager,
    SessionManagerConfig,
)

# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def exec_in_container(
    docker_client: Any, container_id: str, code: str
) -> dict[str, Any]:
    """Execute Python code inside the container via docker exec.

    Returns the exit code and output. Useful for integration tests
    that need to verify container-side behavior directly.
    """
    result = docker_client.containers.get(container_id).exec_run(
        ["python3", "-c", code]
    )
    output = (
        result.output.decode("utf-8")
        if isinstance(result.output, bytes)
        else result.output
    )
    return {
        "exit_code": result.exit_code,
        "output": output,
    }


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def docker_available() -> bool:
    """Check if Docker daemon is available and the image exists.

    Returns False (and skips all Docker-dependent tests) if Docker is
    not reachable or ``sandbox-base:3.12`` is not present.
    """
    import docker

    try:
        client = docker.from_env()
        client.ping()
        # Verify the prebuilt image exists — no building in tests
        client.images.get("sandbox-base:3.12")
        return True
    except Exception:
        return False


@pytest.fixture
def session_manager(docker_available: bool) -> SessionManager:
    """Create a SessionManager with a real Docker client.

    Function-scoped so each test gets a clean SessionManager.
    Uses the prebuilt ``sandbox-base:3.12`` image.
    """
    if not docker_available:
        pytest.skip("Docker or sandbox-base:3.12 image not available")

    import tempfile

    import docker

    raw_client = docker.from_env()
    data_dir = Path(tempfile.mkdtemp(prefix="sess_data_"))
    config = SessionManagerConfig(
        data_dir=data_dir,
        image_registry={
            "3.12": "sandbox-base:3.12",
        },
        default_python_version="3.12",
        network_name="bridge",
        container_user="1000",
    )
    adapter = RealDockerClient(raw_client)
    return SessionManager(docker=adapter, config=config)


@pytest.fixture
def session(session_manager: SessionManager) -> str:
    """Create a session and yield its ID, then tear it down.

    Function-scoped: each test gets its own container, automatically
    cleaned up after the test completes.
    """
    session_id = session_manager.create_session(python_version="3.12")
    yield session_id
    session_manager.end_session(session_id)
