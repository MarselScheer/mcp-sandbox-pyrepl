"""Unit tests for MCPToolHandler error handling and feature paths.

Tests the ``MCPToolHandler`` behavior for:
- Session corruption recovery (restart after ``session_corrupted`` flag)
- Package install exception handling (``send_rpc`` raises → returns error, still disconnects)

These tests use minimal fake SessionManagers — no Docker, no containers, fast.
"""

from __future__ import annotations

from typing import Any

import pytest

from mcp_server import MCPToolHandler


@pytest.fixture
def dummy_image_registry() -> dict[str, str]:
    """Minimal image registry for tests that don't exercise version listing."""
    return {}


class FakeSessionManager:
    """Minimal SessionManager fake for MCPToolHandler tests.

    Only implements the methods that ``MCPToolHandler`` actually calls
    during the tested code paths. Duck-typed — no inheritance needed.
    """

    def __init__(self) -> None:
        self.last_restarted_session_id: str | None = None
        self.network_calls: list[tuple[str, str]] = []
        self._send_exec_result: dict[str, Any] = {}
        self._send_rpc_raises: type[Exception] | None = None

    def send_exec(
        self, session_id: str, code: str, timeout: float = 30.0
    ) -> dict[str, Any]:
        return self._send_exec_result

    def restart_session(self, session_id: str) -> None:
        self.last_restarted_session_id = session_id

    def network_connect(self, session_id: str) -> None:
        self.network_calls.append(("connect", session_id))

    def network_disconnect(self, session_id: str) -> None:
        self.network_calls.append(("disconnect", session_id))

    def send_rpc(self, session_id: str, request: dict[str, Any]) -> dict[str, Any]:
        if self._send_rpc_raises:
            raise self._send_rpc_raises("Simulated RPC failure")
        return {"error": None, "stdout": "", "stderr": ""}

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return None


# ──────────────────────────────────────────────────────────────────────
# Tests: Session corruption recovery
# ──────────────────────────────────────────────────────────────────────


class TestExecutePythonCorruptedSession:
    """execute_python restarts session on corruption flag."""

    def test_corrupted_session_triggers_restart(
        self, dummy_image_registry: dict[str, str]
    ) -> None:
        fake = FakeSessionManager()
        fake._send_exec_result = {
            "stdout": "",
            "stderr": "",
            "display": [],
            "error": "Execution timed out and thread could not be interrupted. "
            "Session may be corrupted.",
            "session_corrupted": True,
        }
        handler = MCPToolHandler(
            session_manager=fake, image_registry=dummy_image_registry
        )

        result = handler.execute_python(
            session_id="sess_test", code="import time; time.sleep(999)"
        )

        # Response should include session_reset flag
        assert result.get("session_reset") is True
        # Session should have been restarted
        assert fake.last_restarted_session_id == "sess_test"

    def test_normal_execution_does_not_trigger_restart(
        self, dummy_image_registry: dict[str, str]
    ) -> None:
        fake = FakeSessionManager()
        fake._send_exec_result = {
            "stdout": "hello\n",
            "stderr": "",
            "display": [],
            "error": None,
        }
        handler = MCPToolHandler(
            session_manager=fake, image_registry=dummy_image_registry
        )

        result = handler.execute_python(session_id="sess_test", code="print('hello')")

        # Response should NOT include session_reset
        assert "session_reset" not in result
        # Session should NOT have been restarted
        assert fake.last_restarted_session_id is None


# ──────────────────────────────────────────────────────────────────────
# Tests: Package install exception handling
# ──────────────────────────────────────────────────────────────────────


class TestInstallPackagesExceptions:
    """install_packages handles send_rpc exceptions gracefully."""

    def test_send_rpc_exception_returns_error(
        self, dummy_image_registry: dict[str, str]
    ) -> None:
        fake = FakeSessionManager()
        fake._send_rpc_raises = RuntimeError
        handler = MCPToolHandler(
            session_manager=fake, image_registry=dummy_image_registry
        )

        result = handler.install_packages(
            session_id="sess_test",
            packages=[{"name": "six"}],
        )

        # Returns structured error, not crash
        assert result["success"] is False
        assert "error" in result
        assert "Simulated RPC failure" in result["error"]

    def test_exception_still_disconnects_network(
        self, dummy_image_registry: dict[str, str]
    ) -> None:
        fake = FakeSessionManager()
        fake._send_rpc_raises = RuntimeError
        handler = MCPToolHandler(
            session_manager=fake, image_registry=dummy_image_registry
        )

        handler.install_packages(
            session_id="sess_test",
            packages=[{"name": "six"}],
        )

        # Connect and disconnect were both called, in the right order
        assert fake.network_calls == [
            ("connect", "sess_test"),
            ("disconnect", "sess_test"),
        ]

    def test_successful_install_disconnects_network(
        self, dummy_image_registry: dict[str, str]
    ) -> None:
        fake = FakeSessionManager()
        fake._send_rpc_raises = None  # No exception — success path
        handler = MCPToolHandler(
            session_manager=fake, image_registry=dummy_image_registry
        )

        handler.install_packages(
            session_id="sess_test",
            packages=[{"name": "six"}],
        )

        # Network was disconnected even on success
        assert ("disconnect", "sess_test") in fake.network_calls
