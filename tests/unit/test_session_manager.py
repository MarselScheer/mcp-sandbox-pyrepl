"""Unit tests for SessionManager error handling paths.

These tests exercise the ``SessionManager`` error paths that never reach
Docker — the error is raised before any Docker method is called. A bare
``object()`` works as the Docker client since it is never actually used.

All tests here are fast: no Docker daemon, no containers, no fixtures.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from session_manager import SessionManager, SessionManagerConfig

# ──────────────────────────────────────────────────────────────────────
# Fake Docker client for file operation error paths
# ──────────────────────────────────────────────────────────────────────


class _FakeContainer:
    """Minimal container-like object returned by ``containers_create``."""

    def __init__(self, container_id: str = "test_cid") -> None:
        self.id = container_id


class _FakeDockerClient:
    """Fake Docker client with configurable ``container_exec_run`` result.

    Supports enough of the ``DockerClient`` protocol to create sessions
    and exercise the file operation error branches.
    """

    def __init__(self, exec_run_result: dict[str, Any] | None = None) -> None:
        self._exec_run_result = exec_run_result or {"exit_code": 0, "output": ""}
        self.exec_run_calls: list[tuple[str, list[str]]] = []

    def containers_create(self, **kwargs: Any) -> _FakeContainer:
        return _FakeContainer()

    def container_get(self, container_id: str) -> _FakeContainer:
        return _FakeContainer(container_id)

    def container_remove(self, container_id: str, force: bool = False) -> None:
        return None

    def container_stop(self, container_id: str) -> None:
        return None

    def container_stdin(self, container_id: str) -> Any:
        from io import StringIO

        return StringIO()

    def container_rpc(
        self, container_id: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        return {}

    def container_exec_run(
        self, container_id: str, cmd: list[str]
    ) -> dict[str, Any]:
        self.exec_run_calls.append((container_id, cmd))
        return self._exec_run_result

    def network_disconnect(self, container_id: str, network: str = "") -> None:
        return None

    def network_connect(self, container_id: str, network: str = "") -> None:
        return None


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _make_manager() -> SessionManager:
    """Create a bare SessionManager with no active sessions.

    The Docker client is ``object()`` — never called by these tests.
    """
    return SessionManager(
        docker=object(),
        config=SessionManagerConfig(
            data_dir=Path("/tmp/test_data"),
            image_registry={"3.12": "sandbox-base:3.12"},
            default_python_version="3.12",
            network_name="bridge",
            container_user="1000",
        ),
    )


def _make_manager_with_session(
    exec_run_result: dict[str, Any] | None = None,
) -> tuple[SessionManager, str]:
    """Create a SessionManager with a single fake session registered.

    Returns ``(manager, session_id)``.  The fake Docker client's
    ``container_exec_run`` returns ``exec_run_result`` (defaults to
    ``{"exit_code": 0, "output": ""}``).
    """
    docker = _FakeDockerClient(exec_run_result=exec_run_result)
    manager = SessionManager(
        docker=docker,
        config=SessionManagerConfig(
            data_dir=Path("/tmp/test_data"),
            image_registry={"3.12": "sandbox-base:3.12"},
            default_python_version="3.12",
            network_name="bridge",
            container_user="1000",
        ),
    )
    session_id = manager.create_session(python_version="3.12")
    return manager, session_id


# ──────────────────────────────────────────────────────────────────────
# Tests: network_connect / network_disconnect with nonexistent session
# ──────────────────────────────────────────────────────────────────────


class TestNetworkError:
    """Network operations on nonexistent sessions."""

    def test_network_connect_nonexistent_session_raises(self) -> None:
        manager = _make_manager()

        with pytest.raises(ValueError, match="Session not found"):
            manager.network_connect("nonexistent")

    def test_network_disconnect_nonexistent_session_raises(self) -> None:
        manager = _make_manager()

        with pytest.raises(ValueError, match="Session not found"):
            manager.network_disconnect("nonexistent")


# ──────────────────────────────────────────────────────────────────────
# Tests: restart_session with nonexistent session
# ──────────────────────────────────────────────────────────────────────


class TestRestartError:
    """Restarting nonexistent sessions."""

    def test_restart_nonexistent_session_raises(self) -> None:
        manager = _make_manager()

        with pytest.raises(ValueError, match="Session not found"):
            manager.restart_session("nonexistent")


# ──────────────────────────────────────────────────────────────────────
# Tests: File operations (write, read, list) with nonexistent session
# ──────────────────────────────────────────────────────────────────────


class TestFileOperationError:
    """File operations on nonexistent sessions return error dicts."""

    def test_write_file_nonexistent_session_returns_error(self) -> None:
        manager = _make_manager()

        result = manager.write_file("nonexistent", "test.txt", "content")

        assert result["success"] is False
        assert "Session not found" in result.get("error", "")

    def test_read_file_nonexistent_session_returns_error(self) -> None:
        manager = _make_manager()

        result = manager.read_file("nonexistent", "test.txt")

        assert "error" in result
        assert "Session not found" in result.get("error", "")

    def test_list_files_nonexistent_session_returns_error(self) -> None:
        manager = _make_manager()

        result = manager.list_files("nonexistent")

        assert "error" in result
        assert "Session not found" in result.get("error", "")


# ──────────────────────────────────────────────────────────────────────
# Tests: write_file exec error branch
# ──────────────────────────────────────────────────────────────────────


class TestWriteFileExecError:
    """write_file when the container's docker exec fails (exit_code != 0)."""

    def test_write_file_exec_error_returns_error(self) -> None:
        manager, session_id = _make_manager_with_session(
            exec_run_result={"exit_code": 1, "output": "boom"}
        )

        result = manager.write_file(session_id, "test.txt", "content")

        assert result["success"] is False
        assert result["error"] == "boom"


# ──────────────────────────────────────────────────────────────────────
# Tests: read_file exec error branch
# ──────────────────────────────────────────────────────────────────────


class TestReadFileExecError:
    """read_file when the container's docker exec fails (exit_code != 0)."""

    def test_read_file_exec_error_returns_error(self) -> None:
        manager, session_id = _make_manager_with_session(
            exec_run_result={"exit_code": 1, "output": "boom"}
        )

        result = manager.read_file(session_id, "test.txt")

        assert "error" in result
        assert result["error"] == "boom"


# ──────────────────────────────────────────────────────────────────────
# Tests: read_file UnicodeDecodeError branch (binary / non-UTF-8 content)
# ──────────────────────────────────────────────────────────────────────


class TestReadFileBinary:
    """read_file when the content is not valid UTF-8 (binary data)."""

    def test_read_file_binary_content_returns_encoded(self) -> None:
        import base64

        # 0xFF 0xFE is invalid UTF-8 — decodes to a UnicodeDecodeError.
        raw_bytes = b"\xff\xfe\x00\x01"
        encoded = base64.b64encode(raw_bytes).decode("ascii")
        output = '{"content": "' + encoded + '"}'

        manager, session_id = _make_manager_with_session(
            exec_run_result={"exit_code": 0, "output": output}
        )

        result = manager.read_file(session_id, "binary.bin")

        # Falls back to returning the base64-encoded content.
        assert result["content"] == encoded


# ──────────────────────────────────────────────────────────────────────
# Tests: read_file JSON/KeyError except branch
# ──────────────────────────────────────────────────────────────────────


class TestReadFileParseError:
    """read_file when the exec output cannot be parsed as the expected JSON."""

    def test_read_file_json_decode_error_returns_error(self) -> None:
        manager, session_id = _make_manager_with_session(
            exec_run_result={"exit_code": 0, "output": "not-json"}
        )

        result = manager.read_file(session_id, "test.txt")

        assert "error" in result
        assert result["error"] == "Failed to parse file content"


# ──────────────────────────────────────────────────────────────────────
# Tests: list_files exec error branch
# ──────────────────────────────────────────────────────────────────────


class TestListFilesExecError:
    """list_files when the container's docker exec fails (exit_code != 0)."""

    def test_list_files_exec_error_returns_error(self) -> None:
        manager, session_id = _make_manager_with_session(
            exec_run_result={"exit_code": 1, "output": "boom"}
        )

        result = manager.list_files(session_id)

        assert "error" in result
        assert result["error"] == "boom"


# ──────────────────────────────────────────────────────────────────────
# Tests: list_files JSONDecodeError branch
# ──────────────────────────────────────────────────────────────────────


class TestListFilesParseError:
    """list_files when the exec output cannot be parsed as JSON."""

    def test_list_files_json_decode_error_returns_error(self) -> None:
        manager, session_id = _make_manager_with_session(
            exec_run_result={"exit_code": 0, "output": "not-json"}
        )

        result = manager.list_files(session_id)

        assert "error" in result
        assert result["error"] == "Failed to parse file listing"

