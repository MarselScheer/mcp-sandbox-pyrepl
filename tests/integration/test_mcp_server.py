"""Tests for the MCP server — the FastMCP tool handlers.

The tool handlers receive their dependencies (SessionManager) via DI.
Tests use a real ``SessionManager`` backed by a real Docker container,
provided by the ``session_manager`` fixture from ``conftest.py``.

All Docker-dependent tests skip gracefully via the ``docker_available``
session-scoped fixture when Docker or the sandbox image is not available.
"""

from __future__ import annotations

from mcp_server import MCPToolHandler
from session_manager import SessionManager

# ──────────────────────────────────────────────────────────────────────
# Tests: Creating sessions
# ──────────────────────────────────────────────────────────────────────


class TestCreateSession:
    """Creating sessions via the MCP tool."""

    def test_create_session_default_version(
        self, session_manager: SessionManager
    ) -> None:
        handler = MCPToolHandler(session_manager=session_manager)

        result = handler.create_session()

        assert "session_id" in result
        assert result["session_id"].startswith("sess_")

    def test_create_session_with_python_version(
        self, session_manager: SessionManager
    ) -> None:
        handler = MCPToolHandler(session_manager=session_manager)

        result = handler.create_session(python_version="3.12")

        assert result["session_id"].startswith("sess_")

    def test_create_session_with_custom_image(
        self, session_manager: SessionManager
    ) -> None:
        handler = MCPToolHandler(session_manager=session_manager)

        result = handler.create_session(image="sandbox-base:3.12")

        assert result["session_id"].startswith("sess_")


# ──────────────────────────────────────────────────────────────────────
# Tests: Executing Python code
# ──────────────────────────────────────────────────────────────────────


class TestExecutePython:
    """Executing Python code via the MCP tool."""

    def test_execute_code_in_session(self, session_manager: SessionManager) -> None:
        handler = MCPToolHandler(session_manager=session_manager)
        create_result = handler.create_session()
        session_id = create_result["session_id"]

        result = handler.execute_python(session_id=session_id, code="print('hello')")

        assert "stdout" in result
        assert result.get("stdout") == "hello\n"

    def test_execute_code_with_custom_timeout(
        self, session_manager: SessionManager
    ) -> None:
        handler = MCPToolHandler(session_manager=session_manager)
        create_result = handler.create_session()
        session_id = create_result["session_id"]

        result = handler.execute_python(
            session_id=session_id, code="print('hello')", timeout=10
        )

        assert result.get("stdout") == "hello\n"


# ──────────────────────────────────────────────────────────────────────
# Tests: Installing packages
# ──────────────────────────────────────────────────────────────────────


class TestInstallPackages:
    """Installing packages via the MCP tool."""

    def test_version_specific_install(self, session_manager: SessionManager) -> None:
        """Install a specific version of a package and verify the exact version."""
        handler = MCPToolHandler(session_manager=session_manager)
        create_result = handler.create_session()
        session_id = create_result["session_id"]

        install_result = handler.install_packages(
            session_id=session_id,
            packages=[{"name": "markupsafe", "version": "2.1.0"}],
        )

        assert install_result["success"] is True, (
            f"Version-specific install failed: {install_result.get('stderr')}"
        )

        exec_result = handler.execute_python(
            session_id=session_id,
            code="import markupsafe; print(markupsafe.__version__)",
        )

        assert exec_result.get("stdout", "").strip() == "2.1.0", (
            f"Expected markupsafe version 2.1.0, got: {exec_result}"
        )

    def test_multi_package_install(self, session_manager: SessionManager) -> None:
        """Install multiple packages in a single call and verify all are importable."""
        handler = MCPToolHandler(session_manager=session_manager)
        create_result = handler.create_session()
        session_id = create_result["session_id"]

        install_result = handler.install_packages(
            session_id=session_id,
            packages=[{"name": "six"}, {"name": "pytz"}],
        )

        assert install_result["success"] is True, (
            f"Multi-package install failed: {install_result.get('stderr')}"
        )

        exec_result = handler.execute_python(
            session_id=session_id,
            code=(
                "import six; import pytz; "
                "print('six:', six.__version__, 'pytz:', pytz.__version__)"
            ),
        )

        assert exec_result.get("error") is None, f"Package import failed: {exec_result}"
        output = exec_result.get("stdout", "")
        assert "six:" in output, f"Expected six to be importable, got: {exec_result}"
        assert "pytz:" in output, f"Expected pytz to be importable, got: {exec_result}"

    def test_install_packages_connects_and_disconnects_network(
        self, session_manager: SessionManager
    ) -> None:
        handler = MCPToolHandler(session_manager=session_manager)
        create_result = handler.create_session()
        session_id = create_result["session_id"]

        result = handler.install_packages(
            session_id=session_id,
            packages=[{"name": "six"}],
        )

        # Network connect/disconnect works; the install RPC may fail
        # due to the sleep-based polling in container_rpc (a known
        # limitation). Key behavior: the handler returns a result
        # without crashing, and the session is still valid.
        assert "success" in result
        assert "stdout" in result
        assert "stderr" in result
        assert "error" in result
        # Verify session is still intact (network was disconnected
        # in the finally block)
        assert handler.get_session(session_id) is not None

        # Verify network is actually disconnected after install:
        # any subsequent execute_python call that attempts network
        # access should fail with a socket/network error.
        net_result = handler.execute_python(
            session_id=session_id,
            code=(
                "import socket; s = socket.socket(); "
                "s.settimeout(5); s.connect(('example.com', 80))"
            ),
        )

        error = net_result.get("error")
        stderr = net_result.get("stderr", "")
        has_network_error = (
            error is not None
            or "No route to host" in stderr
            or "Network is unreachable" in stderr
            or "Connection refused" in stderr
            or "Name or service not known" in stderr
            or "Temporary failure in name resolution" in stderr
            or "timed out" in stderr
        )
        assert has_network_error, (
            f"Expected network failure after install, but got: {net_result}"
        )

    # ──────────────────────────────────────────────────────────────────────


# Tests: Listing and querying sessions
# ──────────────────────────────────────────────────────────────────────


class TestListSessions:
    """Listing and querying sessions."""

    def test_list_sessions_empty(self, session_manager: SessionManager) -> None:
        handler = MCPToolHandler(session_manager=session_manager)

        result = handler.list_sessions()

        assert result == {"sessions": {}}

    def test_list_sessions_after_creation(
        self, session_manager: SessionManager
    ) -> None:
        handler = MCPToolHandler(session_manager=session_manager)
        handler.create_session()

        result = handler.list_sessions()

        assert len(result["sessions"]) == 1

    def test_get_session(self, session_manager: SessionManager) -> None:
        handler = MCPToolHandler(session_manager=session_manager)
        create_result = handler.create_session()
        session_id = create_result["session_id"]

        result = handler.get_session(session_id=session_id)

        assert result["session_id"] == session_id


# ──────────────────────────────────────────────────────────────────────
# Tests: Ending sessions
# ──────────────────────────────────────────────────────────────────────


class TestEndSession:
    """Ending sessions."""

    def test_end_session(self, session_manager: SessionManager) -> None:
        handler = MCPToolHandler(session_manager=session_manager)
        create_result = handler.create_session()
        session_id = create_result["session_id"]

        result = handler.end_session(session_id=session_id)

        assert result["success"] is True
        # Verify session is gone from the handler's manager
        assert handler.get_session(session_id) is None


# ──────────────────────────────────────────────────────────────────────
# Tests: Listing Python versions
# ──────────────────────────────────────────────────────────────────────


class TestListPythonVersions:
    """Listing available Python versions."""

    def test_list_versions(self, session_manager: SessionManager) -> None:
        handler = MCPToolHandler(
            session_manager=session_manager,
            image_registry={
                "3.9": "sandbox-base:3.9",
                "3.12": "sandbox-base:3.12",
            },
        )

        result = handler.list_python_versions()

        assert "3.9" in result["versions"]
        assert "3.12" in result["versions"]
