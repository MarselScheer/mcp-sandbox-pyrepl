"""Tests for SessionManager — the host-side Docker container lifecycle manager.

The SessionManager receives a Docker client via dependency injection (Protocol).
Tests use a real ``SessionManager`` backed by a real Docker container,
provided by the ``session_manager`` fixture from ``conftest.py``.

All Docker-dependent tests skip gracefully using the ``docker_available``
session-scoped fixture when Docker or the sandbox image are not available.
"""

from __future__ import annotations

from typing import Any

import pytest

from session_manager import SessionManager, SessionManagerConfig

# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _get_container_id(mgr: SessionManager, session_id: str) -> str:
    """Helper to get the internal container_id for a session."""
    info = mgr.get_session(session_id)
    assert info is not None
    return info["container_id"]


def _exec_in_container_raw(container_id: str, code: str) -> dict[str, Any]:
    """Execute Python code inside the container via docker exec."""
    import docker as docker_py

    client = docker_py.from_env()
    result = client.containers.get(container_id).exec_run(["python3", "-c", code])
    output = (
        result.output.decode("utf-8")
        if isinstance(result.output, bytes)
        else result.output
    )
    return {
        "exit_code": result.exit_code,
        "output": output,
    }


# ──────────────────────────────────────────────────────────────────────
# Tests: Creating sessions
# ──────────────────────────────────────────────────────────────────────


class TestSessionManagerCreate:
    """Creating sessions — the core lifecycle operation."""

    def test_create_session_returns_session_id(
        self, session_manager: SessionManager
    ) -> None:
        session_id = session_manager.create_session(python_version="3.12")

        assert session_id.startswith("sess_")
        assert len(session_id) > 5

    def test_create_session_creates_container(
        self, session_manager: SessionManager
    ) -> None:
        session_id = session_manager.create_session(python_version="3.12")

        sessions = session_manager.list_sessions()
        assert session_id in sessions

    def test_create_session_with_invalid_version_raises_error(
        self, session_manager: SessionManager
    ) -> None:
        with pytest.raises(ValueError, match="2.7"):
            session_manager.create_session(python_version="2.7")

    def test_create_session_with_custom_image(
        self, session_manager: SessionManager
    ) -> None:
        session_id = session_manager.create_session(image="sandbox-base:3.12")

        info = session_manager.get_session(session_id)
        assert info is not None
        assert info["image"] == "sandbox-base:3.12"

    def test_create_session_runs_as_non_root(
        self, session_manager: SessionManager
    ) -> None:
        session_id = session_manager.create_session(python_version="3.12")
        cid = _get_container_id(session_manager, session_id)

        result = _exec_in_container_raw(
            cid,
            "import os; print(os.getuid())",
        )

        assert result["exit_code"] == 0
        assert result["output"].strip() == "1000"

    def test_create_session_read_only_rootfs(
        self, session_manager: SessionManager
    ) -> None:
        session_id = session_manager.create_session(python_version="3.12")
        cid = _get_container_id(session_manager, session_id)

        result = _exec_in_container_raw(
            cid,
            "try:\n"
            "    with open('/etc/test_write', 'w') as f:\n"
            "        f.write('x')\n"
            "    print('WRITABLE')\n"
            "except OSError:\n"
            "    print('READ_ONLY')\n",
        )

        assert result["output"].strip() == "READ_ONLY"

    def test_create_session_drops_all_capabilities(
        self, session_manager: SessionManager
    ) -> None:
        session_id = session_manager.create_session(python_version="3.12")
        cid = _get_container_id(session_manager, session_id)

        # Verify via /proc/self/status capabilities
        result = _exec_in_container_raw(
            cid,
            "with open('/proc/self/status') as f:\n"
            "    for line in f:\n"
            "        if line.startswith('CapPrm:'):\n"
            "            cap_val = int(line.split(':')[1].strip(), 16)\n"
            "            print(f'caps={cap_val}')\n"
            "            break\n",
        )

        assert result["exit_code"] == 0
        cap_val = int(result["output"].strip().split("=")[1])
        # With cap_drop ALL, effective capability set should be 0
        # (or very minimal — bounding set minimums)
        assert cap_val == 0, f"Expected no capabilities, got {cap_val}"

    def test_create_session_uses_named_volumes(
        self, session_manager: SessionManager
    ) -> None:
        """Both /data and /session use named volumes (no host bind mounts)."""
        session_id = session_manager.create_session(python_version="3.12")
        cid = _get_container_id(session_manager, session_id)

        # Verify /data and /session are writable
        for mount_point in ["/data", "/session"]:
            result = _exec_in_container_raw(
                cid,
                f"import os\n"
                f"test_file = '{mount_point}/.test_write'\n"
                f"try:\n"
                f"    with open(test_file, 'w') as f:\n"
                f"        f.write('ok')\n"
                f"    os.remove(test_file)\n"
                f"    print('WRITABLE')\n"
                f"except OSError as e:\n"
                f"    print(f'ERROR: {{e}}')\n",
            )
            assert result["output"].strip() == "WRITABLE", (
                f"{mount_point} is not writable: {result['output']}"
            )

    def test_create_session_no_host_filesystem_access(
        self, session_manager: SessionManager
    ) -> None:
        """Regression test for Docker-in-Docker bind mount error.

        Uses a home-directory-based data_dir — this would fail with bind mounts.
        Must not raise PermissionError or any OSError.
        """
        from pathlib import Path

        sm = SessionManager(
            docker=session_manager._docker,
            config=SessionManagerConfig(
                data_dir=Path("/home/ubuntu/repos/mcp-sandbox-pyrepl/data"),
                image_registry={"3.12": "sandbox-base:3.12"},
                default_python_version="3.12",
                network_name="bridge",
                container_user="1000",
            ),
        )

        session_id = sm.create_session(python_version="3.12")
        assert session_id.startswith("sess_")

    def test_create_session_adds_to_registry(
        self, session_manager: SessionManager
    ) -> None:
        session_id = session_manager.create_session(python_version="3.12")

        sessions = session_manager.list_sessions()
        assert session_id in sessions


# ──────────────────────────────────────────────────────────────────────
# Tests: Ending sessions
# ──────────────────────────────────────────────────────────────────────


class TestSessionManagerEnd:
    """Ending sessions — cleanup lifecycle."""

    def test_end_session_removes_from_registry(
        self, session_manager: SessionManager
    ) -> None:
        session_id = session_manager.create_session(python_version="3.12")

        session_manager.end_session(session_id)

        assert session_id not in session_manager.list_sessions()

    def test_end_session_is_idempotent(self, session_manager: SessionManager) -> None:
        session_id = session_manager.create_session(python_version="3.12")

        session_manager.end_session(session_id)
        session_manager.end_session(session_id)


# ──────────────────────────────────────────────────────────────────────
# Tests: Listing and querying sessions
# ──────────────────────────────────────────────────────────────────────


class TestSessionManagerList:
    """Listing and querying sessions."""

    def test_list_sessions_empty_initially(
        self, session_manager: SessionManager
    ) -> None:
        assert session_manager.list_sessions() == {}

    def test_list_sessions_after_creation(
        self, session_manager: SessionManager
    ) -> None:
        sid = session_manager.create_session(python_version="3.12")
        sessions = session_manager.list_sessions()

        assert sid in sessions
        info = sessions[sid]
        assert info["python_version"] == "3.12"

    def test_get_session_returns_metadata(
        self, session_manager: SessionManager
    ) -> None:
        sid = session_manager.create_session(python_version="3.12")
        info = session_manager.get_session(sid)

        assert info["session_id"] == sid
        assert info["python_version"] == "3.12"

    def test_get_session_nonexistent_returns_none(
        self, session_manager: SessionManager
    ) -> None:
        assert session_manager.get_session("nonexistent") is None


# ──────────────────────────────────────────────────────────────────────
# Tests: Network connect/disconnect
# ──────────────────────────────────────────────────────────────────────


class TestSessionManagerNetwork:
    """Network connect/disconnect for package installation."""

    def test_network_connect(self, session_manager: SessionManager) -> None:
        sid = session_manager.create_session(python_version="3.12")

        # Connect should succeed without error
        session_manager.network_connect(sid)

    def test_network_disconnect(self, session_manager: SessionManager) -> None:
        sid = session_manager.create_session(python_version="3.12")
        session_manager.network_connect(sid)

        # Disconnect should succeed without error
        session_manager.network_disconnect(sid)


# ──────────────────────────────────────────────────────────────────────
# Tests: Sending code execution
# ──────────────────────────────────────────────────────────────────────


class TestSessionManagerExec:
    """Sending code execution via JSON-RPC."""

    def test_send_exec_raises_on_nonexistent_session(
        self, session_manager: SessionManager
    ) -> None:
        with pytest.raises(ValueError, match="Session not found"):
            session_manager.send_exec("nonexistent", "print('hi')")

    def test_send_rpc_raises_on_nonexistent_session(
        self, session_manager: SessionManager
    ) -> None:
        with pytest.raises(ValueError, match="Session not found"):
            session_manager.send_rpc(
                "nonexistent",
                {"jsonrpc": "2.0", "id": 1, "method": "exec", "params": {}},
            )


# ──────────────────────────────────────────────────────────────────────
# Tests: Container restart on corruption
# ──────────────────────────────────────────────────────────────────────


class TestSessionManagerRestart:
    """Container restart on corruption."""

    def test_restart_container_kills_and_recreates(
        self, session_manager: SessionManager
    ) -> None:
        sid = session_manager.create_session(python_version="3.12")
        original_info = session_manager.get_session(sid)
        assert original_info is not None
        original_cid = original_info["container_id"]

        session_manager.restart_session(sid)

        new_info = session_manager.get_session(sid)
        assert new_info is not None
        assert new_info["container_id"] != original_cid
        assert new_info["status"] == "restarted"
        assert sid in session_manager.list_sessions()
