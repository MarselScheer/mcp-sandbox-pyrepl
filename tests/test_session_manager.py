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

    def test_create_session_mounts_data_and_session_volumes(self) -> None:
        docker = FakeDockerClient()
        mgr = SessionManager(
            docker=docker,
            config=SessionManagerConfig(
                data_dir=Path("/tmp/test-data"),
            ),
        )

        session_id = mgr.create_session(python_version="3.12")

        create_args = docker.created_containers[0]
        volumes = create_args["volumes"]
        assert volumes is not None
        data_binds = [v for v in volumes if v["container_path"] == "/data"]
        assert len(data_binds) == 1
        assert session_id in data_binds[0]["host_path"]

    def test_create_session_adds_to_registry(self) -> None:
        docker = FakeDockerClient()
        mgr = SessionManager(docker=docker)

        session_id = mgr.create_session(python_version="3.12")

        sessions = mgr.list_sessions()
        assert session_id in sessions


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


class TestSessionManagerRestart:
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
