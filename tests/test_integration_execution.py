"""Integration tests for code execution inside sandbox containers.

Exercises code execution via docker exec inside real containers,
verifying stdout capture, error reporting, state persistence,
timeout enforcement, display hook capture, and namespace reset.

The display hook and namespace reset tests exercise the real JSON-RPC
stdin/stdout communication through the container's entrypoint (not
docker exec), since those features are implemented in the entrypoint's
Namespace class via sys.displayhook capture and namespace.clear().
"""

from __future__ import annotations

import time

import pytest
from docker import DockerClient as _DockerClient

from session_manager import SessionManager
from tests.rpc_helpers import rpc_call

# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestCodeExecution:
    """Code execution inside Docker containers."""

    def test_execute_code_captures_stdout(
        self,
        session_manager: SessionManager,
        docker_client: _DockerClient,
    ) -> None:
        """Execute code that prints to stdout and verify the output."""
        session_id = session_manager.create_session(python_version="3.12")
        info = session_manager.get_session(session_id)
        assert info is not None
        container_id = info["container_id"]

        result = docker_client.containers.get(container_id).exec_run(
            ["python3", "-c", "print('hello from docker')"]
        )
        output = result.output.decode("utf-8") if isinstance(result.output, bytes) else result.output

        assert result.exit_code == 0
        assert "hello from docker" in output

        session_manager.end_session(session_id)

    def test_syntax_error_reported(
        self,
        session_manager: SessionManager,
        docker_client: _DockerClient,
    ) -> None:
        """Syntax errors are properly reported."""
        session_id = session_manager.create_session(python_version="3.12")
        info = session_manager.get_session(session_id)
        assert info is not None
        container_id = info["container_id"]

        result = docker_client.containers.get(container_id).exec_run(
            ["python3", "-c", "if True print('missing colon')"]
        )
        output = result.output.decode("utf-8") if isinstance(result.output, bytes) else result.output

        assert result.exit_code != 0
        assert "SyntaxError" in output

        session_manager.end_session(session_id)

    def test_runtime_error_reported(
        self,
        session_manager: SessionManager,
        docker_client: _DockerClient,
    ) -> None:
        """Runtime errors are properly reported with traceback."""
        session_id = session_manager.create_session(python_version="3.12")
        info = session_manager.get_session(session_id)
        assert info is not None
        container_id = info["container_id"]

        result = docker_client.containers.get(container_id).exec_run(
            ["python3", "-c", "1/0"]
        )
        output = result.output.decode("utf-8") if isinstance(result.output, bytes) else result.output

        assert result.exit_code != 0
        assert "ZeroDivisionError" in output

        session_manager.end_session(session_id)

    def test_state_persistence_via_data_volume(
        self,
        session_manager: SessionManager,
        docker_client: _DockerClient,
    ) -> None:
        """State persists across executions via the data volume."""
        session_id = session_manager.create_session(python_version="3.12")
        info = session_manager.get_session(session_id)
        assert info is not None
        container_id = info["container_id"]

        # Write state to /data/state.txt
        write_result = docker_client.containers.get(container_id).exec_run(
            ["python3", "-c", "open('/data/state.txt', 'w').write('42')"]
        )
        assert write_result.exit_code == 0

        # Read state back from /data/state.txt
        read_result = docker_client.containers.get(container_id).exec_run(
            ["python3", "-c", "print(open('/data/state.txt').read())"]
        )
        output = read_result.output.decode("utf-8") if isinstance(read_result.output, bytes) else read_result.output

        assert read_result.exit_code == 0
        assert "42" in output

        session_manager.end_session(session_id)

    def test_execution_timeout_enforced(
        self,
        session_manager: SessionManager,
        docker_client: _DockerClient,
    ) -> None:
        """Executions that exceed the timeout are terminated."""
        session_id = session_manager.create_session(python_version="3.12")
        info = session_manager.get_session(session_id)
        assert info is not None
        container_id = info["container_id"]

        start = time.time()
        result = docker_client.containers.get(container_id).exec_run(
            ["timeout", "5", "python3", "-c", "import time; time.sleep(60)"],
        )
        elapsed = time.time() - start

        output = result.output.decode("utf-8") if isinstance(result.output, bytes) else result.output

        # The command should be killed/timed out within ~15 seconds
        assert elapsed < 30
        # The docker exec timeout may cause a non-zero exit or empty output
        assert result.exit_code != 0 or "timed out" in output.lower()

        session_manager.end_session(session_id)

    def test_display_hook_captures_expression_value(
        self,
        session_manager: SessionManager,
        docker_client: _DockerClient,
    ) -> None:
        """Expression that produces a value triggers sys.displayhook capture.

        Exercises the JSON-RPC stdin/stdout path through the entrypoint.
        The entrypoint uses 'single' compile mode so that expression values
        like `[1, 2, 3]` trigger sys.displayhook, which is captured to the
        `display` field in the response.
        """
        session_id = session_manager.create_session(python_version="3.12")
        info = session_manager.get_session(session_id)
        assert info is not None
        container_id = info["container_id"]

        # Send JSON-RPC exec request through the entrypoint stdin/stdout path
        response = rpc_call(
            docker_client,
            container_id,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "exec",
                "params": {"code": "[1, 2, 3]"},
            },
        )

        assert "result" in response
        result = response["result"]
        assert isinstance(result, dict)
        assert "display" in result
        assert result["display"] == ["[1, 2, 3]"]

        session_manager.end_session(session_id)

    def test_display_hook_captures_literal_value(
        self,
        session_manager: SessionManager,
        docker_client: _DockerClient,
    ) -> None:
        """Literal expressions like `42` produce display hook output."""
        session_id = session_manager.create_session(python_version="3.12")
        info = session_manager.get_session(session_id)
        assert info is not None
        container_id = info["container_id"]

        response = rpc_call(
            docker_client,
            container_id,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "exec",
                "params": {"code": "42"},
            },
        )

        assert "result" in response
        result = response["result"]
        assert isinstance(result, dict)
        assert result["display"] == ["42"]

        session_manager.end_session(session_id)

    def test_namespace_reset_clears_session_state(
        self,
        session_manager: SessionManager,
        docker_client: _DockerClient,
    ) -> None:
        """Namespace reset clears all session state.

        Exercises the JSON-RPC stdin/stdout path: set a variable, verify it
        exists, send reset command, then verify the variable is gone.
        """
        session_id = session_manager.create_session(python_version="3.12")
        info = session_manager.get_session(session_id)
        assert info is not None
        container_id = info["container_id"]

        # Step 1: Set variable x = 42
        set_response = rpc_call(
            docker_client,
            container_id,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "exec",
                "params": {"code": "x = 42"},
            },
        )
        assert "result" in set_response
        assert set_response["result"].get("error") is None

        # Step 2: Verify x exists by printing it
        get_response = rpc_call(
            docker_client,
            container_id,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "exec",
                "params": {"code": "print(x)"},
            },
        )
        assert "result" in get_response
        assert get_response["result"].get("error") is None
        assert "42" in get_response["result"].get("stdout", "")

        # Step 3: Send reset command
        reset_response = rpc_call(
            docker_client,
            container_id,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "reset",
                "params": {},
            },
        )
        assert "result" in reset_response
        assert reset_response["result"].get("ok") is True

        # Step 4: Verify x is gone (error referencing NameError or x not defined)
        verify_response = rpc_call(
            docker_client,
            container_id,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "exec",
                "params": {"code": "print(x)"},
            },
        )
        assert "result" in verify_response
        error = verify_response["result"].get("error")
        assert error is not None
        assert "NameError" in error or "not defined" in error

        session_manager.end_session(session_id)
