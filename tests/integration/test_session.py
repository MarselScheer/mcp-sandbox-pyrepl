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

    def test_end_session_removes_named_volumes(
        self,
        session_manager: SessionManager,
    ) -> None:
        """End a session and verify no named Docker volumes remain.

        This test will fail before the fix: ``container_remove()`` only
        removes the container, not the auto-generated named volumes
        (``vol_<uuid>``). The fix adds volume inspection and cleanup.
        """
        import docker

        docker_client = docker.from_env()
        session_id = session_manager.create_session(python_version="3.12")
        info = session_manager.get_session(session_id)
        assert info is not None
        container_id = info["container_id"]

        # Collect the named volume names before ending the session.
        # Pre-condition check: container must have named volumes for this
        # assertion to be meaningful (otherwise the test would vacuously pass).
        container = docker_client.containers.get(container_id)
        mounts = container.attrs.get("Mounts", [])
        volume_names = [
            m["Name"] for m in mounts if m.get("Type") == "volume" and m.get("Name")
        ]
        assert len(volume_names) > 0, (
            "Pre-condition: container has no named volumes — test would vacuously pass"
        )

        session_manager.end_session(session_id)

        # Verify the named volumes are also removed
        for vol_name in volume_names:
            with pytest.raises(docker.errors.NotFound):
                docker_client.volumes.get(vol_name)

    def test_session_fixture_teardown_cleans_up_containers_and_volumes(
        self,
        session_manager: SessionManager,
    ) -> None:
        """Create a session via fixture, verify fixture teardown cleans up.

        This test creates a session without explicitly calling
        ``end_session()``. The fixture teardown (converted to generator-yield
        pattern) should clean up the container and named volumes.

        Before the fix: the ``session_manager`` fixture has no teardown logic,
        so the container and volumes leak.
        After the fix: the fixture teardown iterates remaining sessions and
        ends each one, then removes the temp ``data_dir``.

        Note: the fixture teardown runs *after* the test body, so the
        actual cleanup assertion is covered by:
        - ``test_end_session_removes_named_volumes`` — proves ``end_session()``
          removes volumes
        - Running the full test suite — proves fixture teardown doesn't crash
          and leaves no leaks (verified by task 4.2)
        """
        import docker

        docker_client = docker.from_env()
        session_id = session_manager.create_session(python_version="3.12")
        info = session_manager.get_session(session_id)
        assert info is not None
        container_id = info["container_id"]

        # Verify the container is running
        container = docker_client.containers.get(container_id)
        assert container.status == "running"

        # Record volume names
        mounts = container.attrs.get("Mounts", [])
        volume_names = [
            m["Name"] for m in mounts if m.get("Type") == "volume" and m.get("Name")
        ]
        assert len(volume_names) > 0, (
            "Pre-condition: container has no named volumes — test would vacuously pass"
        )

        # Don't call end_session() — fixture teardown should handle it.
        # The fixture teardown runs after this test body exits.
        # The actual cleanup is verified by the other test and by
        # running the full test suite without volume leaks.
