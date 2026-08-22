"""Unit tests for SessionManager error handling paths.

These tests exercise the ``SessionManager`` error paths that never reach
Docker — the error is raised before any Docker method is called. A bare
``object()`` works as the Docker client since it is never actually used.

All tests here are fast: no Docker daemon, no containers, no fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from session_manager import SessionManager, SessionManagerConfig

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