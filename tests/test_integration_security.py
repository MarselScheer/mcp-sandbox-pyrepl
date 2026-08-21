"""Integration tests for security constraints on sandbox containers.

Validates non-root execution, filesystem isolation, network isolation,
and session separation.
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
class TestSecurityConstraints:
    """Security constraints on Docker containers."""

    def test_container_runs_as_non_root(
        self,
        session_manager: SessionManager,
    ) -> None:
        """Container runs as non-root user (UID 1000)."""
        session_id = session_manager.create_session(python_version="3.12")
        info = session_manager.get_session(session_id)
        assert info is not None
        container_id = info["container_id"]
        docker_client = docker.from_env()

        result = docker_client.containers.get(container_id).exec_run(
            ["python3", "-c", "import os; print(os.getuid())"]
        )
        output = _decode_output(result)

        assert result.exit_code == 0, f"Failed to get UID: {output}"
        assert "1000" in output, (
            f"Expected UID 1000, got: {output.strip()}"
        )

        session_manager.end_session(session_id)

    def test_writing_outside_data_fails(
        self,
        session_manager: SessionManager,
    ) -> None:
        """Writing outside /data/ fails with permission error."""
        session_id = session_manager.create_session(python_version="3.12")
        info = session_manager.get_session(session_id)
        assert info is not None
        container_id = info["container_id"]
        docker_client = docker.from_env()

        result = docker_client.containers.get(container_id).exec_run(
            [
                "python3", "-c",
                "open('/home/sandbox/test.txt', 'w').write('should fail')",
            ]
        )
        output = _decode_output(result)

        # Should fail because container has read-only rootfs.
        # /tmp is writable (tmpfs mount), but /home/sandbox is on the
        # read-only rootfs.
        assert result.exit_code != 0
        error_keywords = [
            "read-only", "permission", "error", "denied",
        ]
        assert any(kw in output.lower() for kw in error_keywords)

        session_manager.end_session(session_id)

    def test_writing_to_data_succeeds(
        self,
        session_manager: SessionManager,
    ) -> None:
        """Writing to /data/ succeeds (writable volume)."""
        session_id = session_manager.create_session(python_version="3.12")
        info = session_manager.get_session(session_id)
        assert info is not None
        container_id = info["container_id"]
        docker_client = docker.from_env()

        result = docker_client.containers.get(container_id).exec_run(
            [
                "python3", "-c",
                "open('/data/test.txt', 'w').write('should succeed'); print('ok')",
            ]
        )
        output = _decode_output(result)

        assert result.exit_code == 0, (
            f"Writing to /data/ failed: {output}"
        )
        assert "ok" in output

        session_manager.end_session(session_id)

    def test_network_isolation_during_execution(
        self,
        session_manager: SessionManager,
    ) -> None:
        """Outbound HTTP fails during code execution (network disconnected)."""
        session_id = session_manager.create_session(python_version="3.12")
        info = session_manager.get_session(session_id)
        assert info is not None
        docker_client = docker.from_env()

        # Disconnect the container's network
        session_manager.network_disconnect(session_id)

        container_id = info["container_id"]
        result = docker_client.containers.get(container_id).exec_run(
            [
                "python3", "-c",
                "import urllib.request; "
                "urllib.request.urlopen('http://example.com', timeout=5)",
            ]
        )
        output = _decode_output(result)

        # Should fail with a network error
        assert result.exit_code != 0
        assert any(
            msg in output.lower()
            for msg in [
                "timeout",
                "connection refused",
                "no route to host",
                "network is unreachable",
                "name or service not known",
                "temporary failure",
            ]
        ), f"Expected network error, got: {output}"

        # Reconnect for cleanup
        session_manager.network_connect(session_id)
        session_manager.end_session(session_id)

    def test_session_isolation_between_sessions(
        self,
        session_manager: SessionManager,
    ) -> None:
        """Separate containers; ending one doesn't affect the other."""
        # Create two sessions
        sid_a = session_manager.create_session(python_version="3.12")
        sid_b = session_manager.create_session(python_version="3.12")

        info_a = session_manager.get_session(sid_a)
        info_b = session_manager.get_session(sid_b)
        assert info_a is not None and info_b is not None
        docker_client = docker.from_env()

        # Verify they have different container IDs
        assert info_a["container_id"] != info_b["container_id"]

        # Both containers should be running
        container_a = docker_client.containers.get(info_a["container_id"])
        container_b = docker_client.containers.get(info_b["container_id"])
        assert container_a.status == "running"
        assert container_b.status == "running"

        # End session A
        session_manager.end_session(sid_a)

        # Session B should still be running
        container_b = docker_client.containers.get(info_b["container_id"])
        assert container_b.status == "running"
        assert sid_b in session_manager.list_sessions()

        # Session A should be gone
        assert sid_a not in session_manager.list_sessions()

        # Cleanup
        session_manager.end_session(sid_b)
