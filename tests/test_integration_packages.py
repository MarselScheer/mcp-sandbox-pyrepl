"""Integration tests for package installation inside sandbox containers.

Tests package installation via uv pip install and package isolation
between independent sessions.
"""

from __future__ import annotations

import docker
import pytest

from session_manager import SessionManager


def _decode_output(result: object) -> str:
    """Decode exec_run output to string if needed."""
    output: bytes | str = result.output  # type: ignore[union-attr]
    return output.decode("utf-8") if isinstance(output, bytes) else output


@pytest.mark.integration
class TestPackageInstallation:
    """Package installation inside Docker containers.

    Uses a class-scoped container for tests that share a container
    (``test_install_and_use_package``). The isolation test keeps its
    own function-scoped ``session_manager`` to create two sessions
    in separate containers.
    """

    def test_install_and_use_package(
        self,
        class_container: dict,
    ) -> None:
        """Install a package and use it in subsequent code execution."""
        container_id = class_container["container_id"]
        docker_client = docker.from_env()

        container = docker_client.containers.get(container_id)

        # Install package via uv pip install inside the session venv.
        # --no-cache is required because the container's rootfs is read-only
        # and uv's default cache dir (/home/sandbox/.cache/uv) is on the
        # read-only rootfs.
        install_result = container.exec_run(
            [
                "uv", "pip", "install", "--no-cache", "pytz",
                "--python", "/session/venv/bin/python",
            ],
        )
        install_output = _decode_output(install_result)
        assert install_result.exit_code == 0, (
            f"Package install failed: {install_output}"
        )

        # Verify the package is available by importing and using it
        venv_env = {
            "VIRTUAL_ENV": "/session/venv",
            "PATH": "/session/venv/bin:/usr/local/bin:/usr/bin:/bin",
        }
        verify_result = container.exec_run(
            [
                "python3", "-c",
                "import pytz; tz = pytz.timezone('UTC'); print(tz.zone)",
            ],
            environment=venv_env,
        )
        verify_output = _decode_output(verify_result)

        assert verify_result.exit_code == 0, (
            f"Package verification failed: {verify_output}"
        )
        assert "UTC" in verify_output

    def test_package_isolation_between_sessions(
        self,
        session_manager: SessionManager,
    ) -> None:
        """Package installed in session A is unavailable in session B.

        Must use its own function-scoped session_manager (not the
        class-scoped container) because it validates cross-session
        isolation using TWO separate sessions.
        """
        # Create two independent sessions
        session_a = session_manager.create_session(python_version="3.12")
        session_b = session_manager.create_session(python_version="3.12")

        info_a = session_manager.get_session(session_a)
        info_b = session_manager.get_session(session_b)
        assert info_a is not None and info_b is not None
        docker_client = docker.from_env()

        container_a = docker_client.containers.get(info_a["container_id"])
        container_b = docker_client.containers.get(info_b["container_id"])

        # Install pytz in session A only.
        # --no-cache is required because the container's rootfs is read-only
        # and uv's default cache dir (/home/sandbox/.cache/uv) is on the
        # read-only rootfs.
        install_result = container_a.exec_run(
            [
                "uv", "pip", "install", "--no-cache", "pytz",
                "--python", "/session/venv/bin/python",
            ],
        )
        install_output = _decode_output(install_result)
        assert install_result.exit_code == 0, (
            f"Package install failed: {install_output}"
        )

        # Verify pytz is available in session A
        venv_env = {
            "VIRTUAL_ENV": "/session/venv",
            "PATH": "/session/venv/bin:/usr/local/bin:/usr/bin:/bin",
        }
        check_a = container_a.exec_run(
            ["python3", "-c", "import pytz; print(pytz.__version__)"],
            environment=venv_env,
        )
        output_a = _decode_output(check_a)
        assert check_a.exit_code == 0, (
            f"Package should be available in session A: {output_a}"
        )

        # Verify pytz is NOT available in session B
        check_b = container_b.exec_run(
            ["python3", "-c", "import pytz"],
            environment=venv_env,
        )
        output_b = _decode_output(check_b)
        assert check_b.exit_code != 0, (
            f"Package should NOT be available in session B: {output_b}"
        )
        assert "ModuleNotFoundError" in output_b or "ImportError" in output_b

        # Cleanup
        session_manager.end_session(session_a)
        session_manager.end_session(session_b)
