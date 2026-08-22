"""Integration tests for session lifecycle.

Tests the full stack: SessionManager → Docker client → real containers.
Exercises create, list, get, and end operations against real Docker.
"""

from __future__ import annotations

import docker
import pytest

from session_manager import SessionManager

# ──────────────────────────────────────────────────────────────────────
# Session creation
# ──────────────────────────────────────────────────────────────────────


class TestSessionCreate:
    """Creating sessions with real Docker containers."""

    def test_create_session_returns_session_id(
        self, session_manager: SessionManager
    ) -> None:
        """Create a session and verify it returns a session ID."""
        session_id = session_manager.create_session(python_version="3.12")

        assert session_id.startswith("sess_")
        assert len(session_id) > 5

    def test_create_session_starts_container(
        self,
        session_manager: SessionManager,
    ) -> None:
        """Create a session and verify the container is actually running."""
        session_id = session_manager.create_session(python_version="3.12")
        info = session_manager.get_session(session_id)
        assert info is not None
        container_id = info["container_id"]

        # Verify the container is running via Docker SDK
        docker_client = docker.from_env()
        container = docker_client.containers.get(container_id)
        assert container.status == "running"

        # Cleanup
        session_manager.end_session(session_id)

    def test_create_session_with_custom_image(
        self,
        session_manager: SessionManager,
    ) -> None:
        """Create a session with a custom image reference."""
        session_id = session_manager.create_session(image="sandbox-base:3.12")
        info = session_manager.get_session(session_id)
        assert info is not None
        assert info["image"] == "sandbox-base:3.12"

        # Cleanup
        session_manager.end_session(session_id)


# ──────────────────────────────────────────────────────────────────────
# Session listing
# ──────────────────────────────────────────────────────────────────────


class TestSessionList:
    """Listing and querying sessions."""

    def test_list_sessions_empty_initially(
        self, session_manager: SessionManager
    ) -> None:
        """No sessions initially."""
        assert session_manager.list_sessions() == {}

    def test_list_sessions_after_creation(
        self, session_manager: SessionManager
    ) -> None:
        """Create a session, verify it appears in list_sessions()."""
        session_id = session_manager.create_session(python_version="3.12")
        sessions = session_manager.list_sessions()
        assert session_id in sessions

        info = sessions[session_id]
        assert info["python_version"] == "3.12"
        assert info["status"] == "running"

        # Cleanup
        session_manager.end_session(session_id)

    def test_list_sessions_multiple(self, session_manager: SessionManager) -> None:
        """Multiple sessions appear in listing."""
        sid1 = session_manager.create_session(python_version="3.12")
        sid2 = session_manager.create_session(python_version="3.12")

        sessions = session_manager.list_sessions()
        assert sid1 in sessions
        assert sid2 in sessions

        # Cleanup
        session_manager.end_session(sid1)
        session_manager.end_session(sid2)

    def test_get_session_returns_metadata(
        self, session_manager: SessionManager
    ) -> None:
        """get_session() returns detailed metadata."""
        session_id = session_manager.create_session(python_version="3.12")
        info = session_manager.get_session(session_id)

        assert info is not None
        assert info["session_id"] == session_id
        assert info["python_version"] == "3.12"
        assert info["status"] == "running"
        assert "container_id" in info
        assert "created_at" in info
        assert "image" in info

        # Cleanup
        session_manager.end_session(session_id)

    def test_get_session_nonexistent_returns_none(
        self, session_manager: SessionManager
    ) -> None:
        """get_session() returns None for nonexistent sessions."""
        assert session_manager.get_session("nonexistent") is None


# ──────────────────────────────────────────────────────────────────────
# Session ending
# ──────────────────────────────────────────────────────────────────────


class TestSessionEnd:
    """Ending sessions."""

    def test_end_session_stops_container(
        self,
        session_manager: SessionManager,
    ) -> None:
        """End a session and verify the container is stopped and removed."""
        session_id = session_manager.create_session(python_version="3.12")
        info = session_manager.get_session(session_id)
        assert info is not None
        container_id = info["container_id"]

        session_manager.end_session(session_id)

        # Verify the container is removed
        # `docker.containers.get()` raises `docker.errors.NotFound`
        # when the container has been removed.
        docker_client = docker.from_env()
        with pytest.raises(docker.errors.NotFound):
            container = docker_client.containers.get(container_id)
            # If the container exists but is stopped, that's also acceptable
            # in some Docker versions; check it's not running
            assert container.status != "running"

    def test_end_session_removes_from_registry(
        self, session_manager: SessionManager
    ) -> None:
        """End a session and verify it's removed from the active list."""
        session_id = session_manager.create_session(python_version="3.12")

        session_manager.end_session(session_id)

        assert session_manager.get_session(session_id) is None
        assert session_id not in session_manager.list_sessions()

    def test_end_session_is_idempotent(self, session_manager: SessionManager) -> None:
        """Ending a session twice succeeds both times."""
        session_id = session_manager.create_session(python_version="3.12")

        session_manager.end_session(session_id)
        session_manager.end_session(session_id)
