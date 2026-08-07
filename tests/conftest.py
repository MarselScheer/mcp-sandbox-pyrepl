"""Shared fixtures for integration tests.

Integration tests exercise the real Docker stack (SessionManager + Docker SDK).
Fixtures are organized with session-scoped caching (image build, Docker client)
and function-scoped isolation (session, session manager).

Design:
- SessionManager gets a RealDockerClient adapter wrapping the docker-py SDK.
- All fixtures are self-skipping when Docker is unavailable.
- Cleanup is guaranteed via pytest fixture finalization.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from docker import DockerClient as _DockerClient
from docker.errors import BuildError

from docker_adapter import RealDockerClient
from session_manager import (
    SessionManager,
    SessionManagerConfig,
)

# ──────────────────────────────────────────────────────────────────────
# Real Docker Client Adapter  (defined in docker_adapter.py)
# ──────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def exec_in_container(
    docker_client: _DockerClient, container_id: str, code: str
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
    """Check if Docker daemon is available.

    Returns False (and skips all integration tests) if Docker is
    not reachable.
    """
    import docker

    try:
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def docker_client(docker_available: bool) -> _DockerClient:
    """Return a real Docker client instance.

    Skips all tests in this session if Docker is unavailable.
    """
    if not docker_available:
        pytest.skip("Docker daemon not available")

    import docker

    return docker.from_env()


@pytest.fixture(scope="session")
def sandbox_image(docker_client: _DockerClient) -> str:
    """Build the sandbox-base:3.12 image.

    Builds from the project's Dockerfile. Session-scoped so the
    image is built once per test run and cached by Docker.
    """
    import docker

    project_root = Path(__file__).resolve().parent.parent
    dockerfile_path = project_root / "images" / "sandbox-base" / "Dockerfile"
    tag = "sandbox-base:3.12"

    try:
        client = docker.from_env()
        image, _ = client.images.build(
            path=str(project_root),
            dockerfile=str(dockerfile_path),
            tag=tag,
            buildargs={"PYTHON_VERSION": "3.12"},
            rm=True,
        )
        return image.tags[0] if image.tags else tag
    except BuildError as exc:
        pytest.skip(f"Failed to build sandbox image: {exc}")
        return tag  # unreachable, keeps type checker happy


@pytest.fixture
def session_manager(
    docker_client: _DockerClient, sandbox_image: str
) -> SessionManager:
    """Create a SessionManager with a real Docker client.

    Function-scoped so each test gets a clean SessionManager.
    Uses the built sandbox image and a temporary data directory.
    """
    import tempfile

    data_dir = Path(tempfile.mkdtemp(prefix="sess_data_"))
    config = SessionManagerConfig(
        data_dir=data_dir,
        image_registry={
            "3.12": sandbox_image,
        },
        default_python_version="3.12",
        network_name="bridge",
        container_user="1000",
    )
    adapter = RealDockerClient(docker_client)
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
