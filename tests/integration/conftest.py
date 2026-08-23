"""Shared fixtures for integration tests.

Integration tests exercise the real Docker stack (SessionManager + Docker SDK).
Fixtures are organized with session-scoped caching (Docker availability check)
and function-scoped isolation (session, session manager).

Design:
- SessionManager gets a RealDockerClient adapter wrapping the docker-py SDK.
- All fixtures are self-skipping when Docker is unavailable.
- Cleanup is guaranteed via pytest fixture finalization.
- The sandbox image (``sandbox-base:3.12``) must be prebuilt via ``make build-image``.
- Timing hooks wrap fixture setup/teardown boundaries with ``time.perf_counter()``
  for per-phase runtime attribution (profile before optimizing).
"""

from __future__ import annotations

import logging
import shutil
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from docker_adapter import RealDockerClient
from session_manager import (
    SessionManager,
    SessionManagerConfig,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def dummy_image_registry() -> dict[str, str]:
    """Minimal image registry for tests that don't exercise version listing."""
    return {}


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
def session_manager(docker_available: bool) -> Generator[SessionManager, None, None]:
    """Create a SessionManager with a real Docker client.

    Function-scoped so each test gets a clean SessionManager.
    Uses the prebuilt ``sandbox-base:3.12`` image.
    Teardown: ends any remaining sessions and removes the data directory.
    """
    if not docker_available:
        pytest.skip("Docker or sandbox-base:3.12 image not available")

    import tempfile

    import docker

    t0 = time.perf_counter()
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
    manager = SessionManager(docker=adapter, config=config)
    elapsed = time.perf_counter() - t0
    logger.info("TIMING session_manager fixture setup: %.3fs", elapsed)

    yield manager

    # Teardown: end any remaining sessions (defensive — catches tests
    # that forget to call end_session()), then remove the data directory.
    for sid in list(manager.list_sessions()):
        manager.end_session(sid)
    shutil.rmtree(data_dir, ignore_errors=True)


@pytest.fixture
def session(session_manager: SessionManager) -> str:
    """Create a session and yield its ID, then tear it down.

    Function-scoped: each test gets its own container, automatically
    cleaned up after the test completes.
    """
    t0 = time.perf_counter()
    session_id = session_manager.create_session(python_version="3.12")
    create_elapsed = time.perf_counter() - t0
    logger.info("TIMING container_create (%s): %.3fs", session_id, create_elapsed)

    yield session_id

    t1 = time.perf_counter()
    session_manager.end_session(session_id)
    teardown_elapsed = time.perf_counter() - t1
    logger.info("TIMING end_session (%s): %.3fs", session_id, teardown_elapsed)


@pytest.fixture(scope="class")
def class_container(docker_available: bool) -> Generator[dict[str, Any], None, None]:
    """Create a single session manager + container for an entire test class.

    Class-scoped: all tests in the class share one container and one
    SessionManager, eliminating per-test container startup overhead.
    Tests that need session isolation should use the function-scoped
    ``session_manager`` or ``session`` fixture instead.

    Yields a dict with keys:
    - ``manager``: the SessionManager instance
    - ``session_id``: the single session ID shared across the class
    - ``container_id``: the Docker container ID
    """
    if not docker_available:
        pytest.skip("Docker or sandbox-base:3.12 image not available")

    import tempfile

    import docker as _docker

    raw_client = _docker.from_env()
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
    manager = SessionManager(docker=adapter, config=config)

    t0 = time.perf_counter()
    session_id = manager.create_session(python_version="3.12")
    create_elapsed = time.perf_counter() - t0
    logger.info("TIMING class_container create: %.3fs", create_elapsed)

    info = manager.get_session(session_id)
    assert info is not None
    container_id = info["container_id"]

    yield {
        "manager": manager,
        "session_id": session_id,
        "container_id": container_id,
    }

    t1 = time.perf_counter()
    manager.end_session(session_id)
    teardown_elapsed = time.perf_counter() - t1
    logger.info("TIMING class_container end: %.3fs", teardown_elapsed)
    shutil.rmtree(data_dir, ignore_errors=True)
