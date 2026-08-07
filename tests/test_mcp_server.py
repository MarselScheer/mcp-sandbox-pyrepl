"""Tests for the MCP server — the FastMCP tool handlers.

The tool handlers receive their dependencies (SessionManager) via DI.
Tests use FakeSessionManager so arrange stays at 1-3 lines with no mock.patch.
"""

from __future__ import annotations

from typing import Any

from mcp_server import MCPToolHandler

# ──────────────────────────────────────────────────────────────────────
# Fake Session Manager
# ──────────────────────────────────────────────────────────────────────


class FakeSessionManager:
    """A fake SessionManager for testing MCP tools.

    No Docker, no containers, no network. Just pure behavior verification.
    """

    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.ended_sessions: list[str] = []
        self.connected_networks: list[str] = []
        self.disconnected_networks: list[str] = []
        self.exec_calls: list[dict[str, Any]] = []
        self.last_create_kwargs: dict[str, Any] = {}

    def create_session(
        self,
        python_version: str | None = None,
        image: str | None = None,
    ) -> str:
        session_id = f"sess_{len(self.sessions) + 1}"
        self.sessions[session_id] = {
            "session_id": session_id,
            "python_version": python_version or "3.12",
            "image": image or "sandbox-base:3.12",
            "container_id": f"container-{len(self.sessions) + 1}",
            "status": "running",
        }
        self.last_create_kwargs = {
            "python_version": python_version,
            "image": image,
        }
        return session_id

    def end_session(self, session_id: str) -> None:
        self.ended_sessions.append(session_id)
        self.sessions.pop(session_id, None)

    def list_sessions(self) -> dict[str, dict[str, Any]]:
        return dict(self.sessions)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return self.sessions.get(session_id)

    def network_connect(self, session_id: str) -> None:
        self.connected_networks.append(session_id)

    def network_disconnect(self, session_id: str) -> None:
        self.disconnected_networks.append(session_id)

    def send_exec(
        self, session_id: str, code: str, timeout: float = 30.0
    ) -> dict[str, Any]:
        self.exec_calls.append(
            {"session_id": session_id, "code": code, "timeout": timeout}
        )
        return {
            "stdout": "",
            "stderr": "",
            "display": [],
            "error": None,
        }

    def send_rpc(
        self, session_id: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        return {}


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


class TestCreateSession:
    """Creating sessions via the MCP tool."""

    def test_create_session_default_version(self) -> None:
        sm = FakeSessionManager()
        handler = MCPToolHandler(session_manager=sm)

        result = handler.create_session()

        assert "session_id" in result
        assert result["session_id"].startswith("sess_")

    def test_create_session_with_python_version(self) -> None:
        sm = FakeSessionManager()
        handler = MCPToolHandler(session_manager=sm)

        handler.create_session(python_version="3.9")

        assert sm.last_create_kwargs["python_version"] == "3.9"

    def test_create_session_with_custom_image(self) -> None:
        sm = FakeSessionManager()
        handler = MCPToolHandler(session_manager=sm)

        handler.create_session(image="my-custom:latest")

        assert sm.last_create_kwargs["image"] == "my-custom:latest"


class TestExecutePython:
    """Executing Python code via the MCP tool."""

    def test_execute_code_in_session(self) -> None:
        sm = FakeSessionManager()
        handler = MCPToolHandler(session_manager=sm)
        session_id = handler.create_session()["session_id"]

        result = handler.execute_python(
            session_id=session_id, code="print('hello')"
        )

        assert "stdout" in result
        assert len(sm.exec_calls) == 1
        assert sm.exec_calls[0]["code"] == "print('hello')"

    def test_execute_code_with_custom_timeout(self) -> None:
        sm = FakeSessionManager()
        handler = MCPToolHandler(session_manager=sm)
        session_id = handler.create_session()["session_id"]

        handler.execute_python(
            session_id=session_id, code="sleep(10)", timeout=5
        )

        assert sm.exec_calls[0]["timeout"] == 5


class TestInstallPackages:
    """Installing packages via the MCP tool."""

    def test_install_packages_connects_and_disconnects_network(self) -> None:
        sm = FakeSessionManager()
        handler = MCPToolHandler(session_manager=sm)
        session_id = handler.create_session()["session_id"]

        handler.install_packages(
            session_id=session_id,
            packages=[{"name": "pandas"}],
        )

        assert session_id in sm.connected_networks
        assert session_id in sm.disconnected_networks

    def test_install_single_package(self) -> None:
        sm = FakeSessionManager()
        handler = MCPToolHandler(session_manager=sm)
        session_id = handler.create_session()["session_id"]

        result = handler.install_packages(
            session_id=session_id,
            packages=[{"name": "numpy"}],
        )

        assert result["success"] is True


class TestListSessions:
    """Listing and querying sessions."""

    def test_list_sessions_empty(self) -> None:
        sm = FakeSessionManager()
        handler = MCPToolHandler(session_manager=sm)

        result = handler.list_sessions()

        assert result == {"sessions": {}}

    def test_list_sessions_after_creation(self) -> None:
        sm = FakeSessionManager()
        handler = MCPToolHandler(session_manager=sm)
        handler.create_session()

        result = handler.list_sessions()

        assert len(result["sessions"]) == 1

    def test_get_session(self) -> None:
        sm = FakeSessionManager()
        handler = MCPToolHandler(session_manager=sm)
        session_id = handler.create_session()["session_id"]

        result = handler.get_session(session_id=session_id)

        assert result["session_id"] == session_id


class TestEndSession:
    """Ending sessions."""

    def test_end_session(self) -> None:
        sm = FakeSessionManager()
        handler = MCPToolHandler(session_manager=sm)
        session_id = handler.create_session()["session_id"]

        result = handler.end_session(session_id=session_id)

        assert result["success"] is True
        assert session_id in sm.ended_sessions


class TestListPythonVersions:
    """Listing available Python versions."""

    def test_list_versions(self) -> None:
        sm = FakeSessionManager()
        handler = MCPToolHandler(
            session_manager=sm,
            image_registry={
                "3.9": "sandbox-base:3.9",
                "3.12": "sandbox-base:3.12",
            },
        )

        result = handler.list_python_versions()

        assert "3.9" in result["versions"]
        assert "3.12" in result["versions"]
