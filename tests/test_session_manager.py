"""Tests for SessionManager — the host-side Docker container lifecycle manager.

The SessionManager receives a Docker client via dependency injection (Protocol).
Tests use FakeDockerClient so arrange stays at 1-3 lines with no mock.patch.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from session_manager import (
    SessionManager,
    SessionManagerConfig,
)

# ──────────────────────────────────────────────────────────────────────
# Fake Docker Client
# ──────────────────────────────────────────────────────────────────────


@dataclass
class FakeContainer:
    """A fake container returned by the fake Docker client."""

    id: str
    image: str
    status: str = "running"
    attached_networks: set[str] | None = None
    stdin: StringIO | None = None
    exec_log: list[list[str]] | None = None

    def __init__(self, container_id: str, image: str) -> None:
        self.id = container_id
        self.image = image
        self.status = "running"
        self.attached_networks = {"bridge"}
        self.stdin = StringIO()
        self.exec_log = []


class FakeDockerClient:
    """A fake Docker client for testing SessionManager.

    No real Docker daemon needed. No mock.patch. Just inject and test.
    """

    def __init__(self) -> None:
        self.containers: dict[str, FakeContainer] = {}
        self.created_containers: list[dict[str, Any]] = []
        self.removed_containers: list[str] = []
        self.network_changes: list[dict[str, Any]] = []
        self.rpc_calls: list[dict[str, Any]] = []

    def containers_create(
        self,
        image: str,
        command: str | None = None,
        name: str | None = None,
        user: str | None = None,
        read_only: bool = False,
        cap_drop: list[str] | None = None,
        volumes: list[dict[str, Any]] | None = None,
        network: str | None = None,
        detach: bool = False,
        tmpfs: dict[str, str] | None = None,
    ) -> FakeContainer:
        container_id = name or f"container-{len(self.containers) + 1}"
        container = FakeContainer(container_id=container_id, image=image)
        container.status = "running"
        container.attached_networks = {network or "bridge"}
        self.containers[container_id] = container
        self.created_containers.append(dict(locals()))
        return container

    def container_get(self, container_id: str) -> FakeContainer:
        container = self.containers.get(container_id)
        if container is None:
            msg = f"Container {container_id} not found"
            raise ValueError(msg)
        return container

    def container_remove(
        self, container_id: str, force: bool = False
    ) -> None:
        _ = force
        self.removed_containers.append(container_id)
        self.containers.pop(container_id, None)

    def container_stop(self, container_id: str) -> None:
        container = self.containers.get(container_id)
        if container:
            container.status = "exited"

    def container_restart(self, container_id: str) -> None:
        pass

    def container_stdin(self, container_id: str) -> StringIO:
        container = self.containers.get(container_id)
        if container is None:
            msg = f"Container {container_id} not found"
            raise ValueError(msg)
        return container.stdin

    def container_exec_run(
        self, container_id: str, cmd: list[str]
    ) -> dict[str, Any]:
        container = self.containers.get(container_id)
        if container is None:
            msg = f"Container {container_id} not found"
            raise ValueError(msg)
        if container.exec_log is not None:
            container.exec_log.append(cmd)
        return {"exit_code": 0, "output": ""}

    def container_rpc(
        self, container_id: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        """Simulate sending a JSON-RPC request and receiving a response."""
        self.rpc_calls.append({"container_id": container_id, "request": request})
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {
                "stdout": "",
                "stderr": "",
                "display": [],
                "error": None,
            },
        }

    def network_disconnect(
        self, container_id: str, network: str = "bridge"
    ) -> None:
        container = self.containers.get(container_id)
        if container and container.attached_networks:
            container.attached_networks.discard(network)
        self.network_changes.append(
            {
                "action": "disconnect",
                "container_id": container_id,
                "network": network,
            }
        )

    def network_connect(
        self, container_id: str, network: str = "bridge"
    ) -> None:
        container = self.containers.get(container_id)
        if container:
            if container.attached_networks is None:
                container.attached_networks = set()
            container.attached_networks.add(network)
        self.network_changes.append(
            {
                "action": "connect",
                "container_id": container_id,
                "network": network,
            }
        )


# ──────────────────────────────────────────────────────────────────────
# Docker-py-style client (mimics real docker-py API surface)
# ──────────────────────────────────────────────────────────────────────


class _DockerPyContainers:
    """Mimics docker-py's ``containers`` namespace (ContainerCollection).

    Has ``.create()`` and ``.get()`` — but the parent ``DockerPyStyleClient``
    does NOT have a ``containers_create()`` method, reproducing exactly the
    interface mismatch between docker-py's namespace API and the Protocol.
    """

    def __init__(self) -> None:
        self._created: list[Any] = []

    def create(
        self,
        image: str,
        command: str | None = None,
        name: str | None = None,
        user: str | None = None,
        read_only: bool = False,
        cap_drop: list[str] | None = None,
        volumes: list[dict[str, Any]] | None = None,
        network: str | None = None,
        detach: bool = False,
        tmpfs: dict[str, str] | None = None,
        stdin_open: bool = False,
    ) -> Any:
        from types import SimpleNamespace

        container_id = name or f"container-{len(self._created) + 1}"
        container = SimpleNamespace(id=container_id, image=image)
        self._created.append(
            {
                "image": image,
                "command": command,
                "name": name,
                "user": user,
                "read_only": read_only,
                "cap_drop": cap_drop,
                "volumes": volumes,
                "network": network,
                "detach": detach,
                "tmpfs": tmpfs,
                "stdin_open": stdin_open,
            }
        )
        return container

    def get(self, container_id: str) -> Any:
        raise ValueError(f"Container {container_id} not found")


class DockerPyStyleClient:
    """Mimics the real docker-py ``docker.DockerClient`` API surface.

    docker-py uses a namespace pattern: ``client.containers.create(...)``
    and ``client.containers.get(...)`` — **not** flat ``containers_create``.

    This class deliberately does NOT implement the ``DockerClient`` Protocol
    (no ``containers_create`` method), so injecting it into ``SessionManager``
    reproduces the exact ``AttributeError`` seen in production.

    This is NOT a fake for testing — it's a reproduction of the bug.
    """

    def __init__(self) -> None:
        self.containers = _DockerPyContainers()


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _container_id(mgr: SessionManager, session_id: str) -> str:
    """Helper to get the internal container_id for a session."""
    info = mgr.get_session(session_id)
    assert info is not None
    return info["container_id"]


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


class TestSessionManagerCreate:
    """Creating sessions — the core lifecycle operation."""

    def test_create_session_returns_session_id(self) -> None:
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)

        session_id = mgr.create_session(python_version="3.12")

        assert session_id.startswith("sess_")
        assert len(session_id) > 5

    def test_create_session_starts_docker_container(self) -> None:
        docker = FakeDockerClient()
        mgr = SessionManager(
            docker=docker,
            config=SessionManagerConfig(
                data_dir=Path("/tmp/test-data"),
                image_registry={"3.12": "sandbox-base:3.12"},
            ),
        )

        mgr.create_session(python_version="3.12")

        assert len(docker.created_containers) == 1
        create_args = docker.created_containers[0]
        assert create_args["image"] == "sandbox-base:3.12"

    def test_create_session_with_invalid_version_raises_error(self) -> None:
        docker = FakeDockerClient()
        mgr = SessionManager(
            docker=docker,
            config=SessionManagerConfig(
                image_registry={"3.12": "sandbox-base:3.12"},
            ),
        )

        with pytest.raises(ValueError, match="2.7"):
            mgr.create_session(python_version="2.7")

    def test_create_session_with_custom_image(self) -> None:
        docker = FakeDockerClient()
        mgr = SessionManager(
            docker=docker,
            config=SessionManagerConfig(
                image_registry={"3.12": "sandbox-base:3.12"}
            ),
        )

        mgr.create_session(image="my-custom:latest")

        assert len(docker.created_containers) == 1
        assert docker.created_containers[0]["image"] == "my-custom:latest"

    def test_create_session_runs_as_non_root(self) -> None:
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)

        mgr.create_session(python_version="3.12")

        create_args = docker.created_containers[0]
        assert create_args["user"] == "1000"

    def test_create_session_with_read_only_rootfs(self) -> None:
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)

        mgr.create_session(python_version="3.12")

        create_args = docker.created_containers[0]
        assert create_args["read_only"] is True

    def test_create_session_with_cap_drop_all(self) -> None:
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)

        mgr.create_session(python_version="3.12")

        create_args = docker.created_containers[0]
        assert create_args["cap_drop"] == ["ALL"]

    def test_create_session_uses_named_volumes_for_data_and_session(
        self,
    ) -> None:
        """Both /data and /session use empty host_path (named volumes).

        This avoids host-side bind mount issues when the MCP server runs
        inside a Docker container (Docker-in-Docker). Named volumes are
        managed entirely by Docker and never resolve paths on the host.
        """
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)

        mgr.create_session(python_version="3.12")

        create_args = docker.created_containers[0]
        volumes = create_args["volumes"]
        assert volumes is not None
        for vol in volumes:
            assert (
                vol["host_path"] == ""
            ), f"Expected named volume for {vol['container_path']}, got bind mount"

    def test_create_session_does_not_access_host_filesystem(self) -> None:
        """Regression test for Docker-in-Docker bind mount error.

        The original bug: create_session called _ensure_data_dir() which
        created a directory under data_dir (e.g., /home/ubuntu/...), then
        bind-mounted that path into the container. When the MCP server ran
        inside a Docker container, the Docker daemon (on the host) tried to
        resolve the bind mount path on the host filesystem — but the path
        only existed inside the IDE container, causing:
        [Errno 13] Permission denied: '/home/ubuntu'

        Fix: Use Docker named volumes for /data instead of host bind mounts.
        This test verifies no host-side filesystem operations are performed
        even when data_dir points to a home-directory path.
        """
        docker = FakeDockerClient()
        # Use a home-directory-based data_dir — this would fail with bind mounts
        mgr = SessionManager(
            docker=docker,
            config=SessionManagerConfig(
                data_dir=Path("/home/ubuntu/repos/mcp-sandbox-pyrepl/data"),
            ),
        )

        # Must not raise PermissionError or any OSError
        session_id = mgr.create_session(python_version="3.12")
        assert session_id.startswith("sess_")

    def test_create_session_adds_to_registry(self) -> None:
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)

        session_id = mgr.create_session(python_version="3.12")

        sessions = mgr.list_sessions()
        assert session_id in sessions

    def test_create_session_fails_with_dockerpy_style_client(
        self,
    ) -> None:
        """Reproduce the production AttributeError.

        The real docker-py client uses a namespace API
        (``client.containers.create``), but the ``DockerClient`` Protocol
        expects a flat method (``client.containers_create``).

        When a docker-py-style object is injected directly (as happens in
        ``main.py`` via ``docker.from_env()``), ``create_session`` raises:

            AttributeError: 'DockerClient' object has no attribute
                           'containers_create'

        This test verifies the error is correctly reproduced — before
        the fix is applied. No Docker daemon needed.
        """
        docker = DockerPyStyleClient()
        mgr = SessionManager(
            docker=docker,
            config=SessionManagerConfig(
                image_registry={"3.12": "sandbox-base:3.12"},
            ),
        )

        with pytest.raises(AttributeError) as exc_info:
            mgr.create_session(python_version="3.12")

        assert "containers_create" in str(exc_info.value)


class TestSessionManagerEnd:
    """Ending sessions — cleanup lifecycle."""

    def test_end_session_stops_and_removes_container(self) -> None:
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)
        session_id = mgr.create_session(python_version="3.12")
        cid = _container_id(mgr, session_id)

        mgr.end_session(session_id)

        assert cid in docker.removed_containers

    def test_end_session_removes_from_registry(self) -> None:
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)
        session_id = mgr.create_session(python_version="3.12")

        mgr.end_session(session_id)

        assert session_id not in mgr.list_sessions()

    def test_end_session_is_idempotent(self) -> None:
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)
        session_id = mgr.create_session(python_version="3.12")

        mgr.end_session(session_id)
        mgr.end_session(session_id)


class TestSessionManagerList:
    """Listing and querying sessions."""

    def test_list_sessions_empty_initially(self) -> None:
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)

        assert mgr.list_sessions() == {}

    def test_list_sessions_after_creation(self) -> None:
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)

        sid = mgr.create_session(python_version="3.12")
        sessions = mgr.list_sessions()

        assert sid in sessions
        info = sessions[sid]
        assert info["python_version"] == "3.12"

    def test_get_session_returns_metadata(self) -> None:
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)

        sid = mgr.create_session(python_version="3.12")
        info = mgr.get_session(sid)

        assert info["session_id"] == sid
        assert info["python_version"] == "3.12"

    def test_get_session_nonexistent_returns_none(self) -> None:
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)

        assert mgr.get_session("nonexistent") is None


class TestSessionManagerNetwork:
    """Network connect/disconnect for package installation."""

    def test_network_connect(self) -> None:
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)
        sid = mgr.create_session(python_version="3.12")
        cid = _container_id(mgr, sid)

        mgr.network_connect(sid)

        connect_ops = [
            n
            for n in docker.network_changes
            if n["action"] == "connect" and n["container_id"] == cid
        ]
        assert len(connect_ops) >= 1

    def test_network_disconnect(self) -> None:
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)
        sid = mgr.create_session(python_version="3.12")
        cid = _container_id(mgr, sid)

        mgr.network_disconnect(sid)

        disconnect_ops = [
            n
            for n in docker.network_changes
            if n["action"] == "disconnect" and n["container_id"] == cid
        ]
        assert len(disconnect_ops) >= 1

    def test_network_after_disconnect_container_has_no_network(self) -> None:
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)
        sid = mgr.create_session(python_version="3.12")
        cid = _container_id(mgr, sid)

        container = docker.container_get(cid)
        assert "bridge" in (container.attached_networks or set())

        mgr.network_disconnect(sid)

        assert "bridge" not in (container.attached_networks or set())


class TestSessionManagerExec:
    """Sending code execution via JSON-RPC."""

    def test_send_exec_calls_container_rpc(self) -> None:
        """send_exec delegates to container_rpc on the Docker client."""
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)
        sid = mgr.create_session(python_version="3.12")
        cid = _container_id(mgr, sid)

        mgr.send_exec(sid, "print('hello')")

        assert len(docker.rpc_calls) == 1
        assert docker.rpc_calls[0]["container_id"] == cid
        assert docker.rpc_calls[0]["request"]["method"] == "exec"
        assert docker.rpc_calls[0]["request"]["params"]["code"] == "print('hello')"

    def test_send_exec_returns_stdout(self) -> None:
        """send_exec returns stdout from the container_rpc response."""
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)
        sid = mgr.create_session(python_version="3.12")

        # Make container_rpc return a known response
        original_rpc = docker.container_rpc

        def patched_rpc(container_id: str, request: dict[str, Any]) -> dict[str, Any]:
            original_rpc(container_id, request)
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "result": {
                    "stdout": "hello\n",
                    "stderr": "",
                    "display": [],
                    "error": None,
                },
            }

        docker.container_rpc = patched_rpc  # type: ignore[assignment]

        result = mgr.send_exec(sid, "print('hello')")

        assert result["stdout"] == "hello\n"

    def test_send_exec_returns_error(self) -> None:
        """send_exec returns error from the container_rpc response."""
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)
        sid = mgr.create_session(python_version="3.12")

        original_rpc = docker.container_rpc

        def patched_rpc(container_id: str, request: dict[str, Any]) -> dict[str, Any]:
            original_rpc(container_id, request)
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "result": {
                    "stdout": "",
                    "stderr": "Traceback...",
                    "display": [],
                    "error": "ZeroDivisionError: division by zero",
                },
            }

        docker.container_rpc = patched_rpc  # type: ignore[assignment]

        result = mgr.send_exec(sid, "1/0")

        assert result["error"] == "ZeroDivisionError: division by zero"

    def test_send_exec_returns_display(self) -> None:
        """send_exec returns display output from the container_rpc response."""
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)
        sid = mgr.create_session(python_version="3.12")

        original_rpc = docker.container_rpc

        def patched_rpc(container_id: str, request: dict[str, Any]) -> dict[str, Any]:
            original_rpc(container_id, request)
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "result": {
                    "stdout": "",
                    "stderr": "",
                    "display": ["42"],
                    "error": None,
                },
            }

        docker.container_rpc = patched_rpc  # type: ignore[assignment]

        result = mgr.send_exec(sid, "42")

        assert result["display"] == ["42"]

    def test_send_exec_raises_on_nonexistent_session(self) -> None:
        """send_exec raises ValueError for non-existent sessions."""
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)

        with pytest.raises(ValueError, match="Session not found"):
            mgr.send_exec("nonexistent", "print('hi')")

    def test_send_rpc_raises_on_nonexistent_session(self) -> None:
        """send_rpc raises ValueError for non-existent sessions."""
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)

        with pytest.raises(ValueError, match="Session not found"):
            mgr.send_rpc(
                "nonexistent",
                {"jsonrpc": "2.0", "id": 1, "method": "exec", "params": {}},
            )
    """Container restart on corruption."""

    def test_restart_container_kills_and_recreates(self) -> None:
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)
        sid = mgr.create_session(python_version="3.12")
        cid = _container_id(mgr, sid)
        original_create_count = len(docker.created_containers)

        mgr.restart_session(sid)

        assert cid in docker.removed_containers
        assert len(docker.created_containers) == original_create_count + 1
