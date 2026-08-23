"""Integration tests for main.py factory functions.

Tests create_docker_client, create_session_manager and create_mcp_app
with real Docker. These factory functions wire up the full stack from
config to Docker client to SessionManager.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from main import (
    create_docker_client,
    create_mcp_app,
    create_session_manager,
)


class TestCreateDockerClient:
    """Creating the Docker client from the factory."""

    def test_create_docker_client_returns_usable_client(
        self, docker_available: bool
    ) -> None:
        """Verify create_docker_client returns a RealDockerClient that works.

        The factory calls ``ping()`` internally, so a successful return
        already proves Docker is reachable. This test goes further — it
        uses the returned client to create and inspect a real sandbox
        container, verifying the adapter is properly wired end-to-end.
        """
        if not docker_available:
            pytest.skip("Docker not available")

        from docker_adapter import RealDockerClient

        client = create_docker_client()

        assert isinstance(client, RealDockerClient)

        # Use the client — create a minimal container and exec
        container = client.containers_create(
            image="sandbox-base:3.12",
            user="1000",
            read_only=True,
            cap_drop=["ALL"],
            detach=True,
        )

        try:
            assert container.id is not None
            assert container.status in ("created", "running")

            # Verify we can get the container back
            fetched = client.container_get(container.id)
            assert fetched.id == container.id

            # Verify we can exec a command in the container
            result = client.container_exec_run(
                container.id, ["python3", "-c", "print('hello from sandbox')"]
            )
            assert result["exit_code"] == 0
            assert "hello from sandbox" in result["output"]
        finally:
            client.container_stop(container.id)
            client.container_remove(container.id, force=True)


class TestCreateSessionManager:
    """Creating the SessionManager from config."""

    def test_create_session_manager_with_config(
        self, docker_available: bool, tmp_path: Path
    ) -> None:
        if not docker_available:
            pytest.skip("Docker not available")
        import docker

        from docker_adapter import RealDockerClient

        config = {
            "sandbox": {
                "images": {"3.12": "sandbox-base:3.12"},
                "defaults": {"python_version": "3.12", "timeout": 30},
                "data_dir": str(tmp_path / "data"),
            }
        }
        raw_client = docker.from_env()
        adapter = RealDockerClient(raw_client)

        sm = create_session_manager(config, docker_client=adapter)

        assert sm is not None
        session_id = sm.create_session(python_version="3.12")
        try:
            assert session_id.startswith("sess_")
        finally:
            sm.end_session(session_id)

    def test_create_session_manager_with_defaults(self, docker_available: bool) -> None:
        if not docker_available:
            pytest.skip("Docker not available")
        import docker

        from docker_adapter import RealDockerClient

        config = {"sandbox": {}}
        raw_client = docker.from_env()
        adapter = RealDockerClient(raw_client)

        sm = create_session_manager(config, docker_client=adapter)

        assert sm is not None


class TestCreateMCPApp:
    """Creating the MCP app from the factory."""

    def test_create_mcp_app_returns_app(
        self, docker_available: bool, tmp_path: Path
    ) -> None:
        if not docker_available:
            pytest.skip("Docker not available")
        import docker

        from docker_adapter import RealDockerClient

        config = {
            "sandbox": {
                "images": {"3.12": "sandbox-base:3.12"},
                "defaults": {"python_version": "3.12", "timeout": 30},
                "data_dir": str(tmp_path / "data"),
            }
        }
        raw_client = docker.from_env()
        adapter = RealDockerClient(raw_client)

        mcp_app = create_mcp_app(config, docker_client=adapter)

        assert mcp_app is not None
