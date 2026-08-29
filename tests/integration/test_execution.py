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

import docker
import pytest

from tests.integration.rpc_helpers import rpc_call


def _decode_output(result: object) -> str:
    """Decode exec_run output to string if needed."""
    output: bytes | str = result.output  # type: ignore[union-attr]
    return output.decode("utf-8") if isinstance(output, bytes) else output


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


class TestCodeExecution:
    """Code execution inside Docker containers.

    Uses a class-scoped container to eliminate per-test container
    startup overhead. All tests share one container; tests that
    exercise container/session lifecycle still use per-test sessions.
    """

    def test_execute_code_captures_stdout(
        self,
        class_container: dict,
    ) -> None:
        """Execute code that prints to stdout and verify the output."""
        container_id = class_container["container_id"]
        docker_client = docker.from_env()

        result = docker_client.containers.get(container_id).exec_run(
            ["python3", "-c", "print('hello from docker')"]
        )
        output = _decode_output(result)

        assert result.exit_code == 0
        assert "hello from docker" in output

    def test_syntax_error_reported(
        self,
        class_container: dict,
    ) -> None:
        """Syntax errors are properly reported."""
        container_id = class_container["container_id"]
        docker_client = docker.from_env()

        result = docker_client.containers.get(container_id).exec_run(
            ["python3", "-c", "if True print('missing colon')"]
        )
        output = _decode_output(result)

        assert result.exit_code != 0
        assert "SyntaxError" in output

    def test_runtime_error_reported(
        self,
        class_container: dict,
    ) -> None:
        """Runtime errors are properly reported with traceback."""
        container_id = class_container["container_id"]
        docker_client = docker.from_env()

        result = docker_client.containers.get(container_id).exec_run(
            ["python3", "-c", "1/0"]
        )
        output = _decode_output(result)

        assert result.exit_code != 0
        assert "ZeroDivisionError" in output

    def test_state_persistence_via_data_volume(
        self,
        class_container: dict,
    ) -> None:
        """State persists across executions via the data volume."""
        container_id = class_container["container_id"]
        docker_client = docker.from_env()

        # Write state to /data/state.txt
        write_result = docker_client.containers.get(container_id).exec_run(
            ["python3", "-c", "open('/data/state.txt', 'w').write('42')"]
        )
        assert write_result.exit_code == 0

        # Read state back from /data/state.txt
        read_result = docker_client.containers.get(container_id).exec_run(
            ["python3", "-c", "print(open('/data/state.txt').read())"]
        )
        output = _decode_output(read_result)

        assert read_result.exit_code == 0
        assert "42" in output

    def test_execution_timeout_enforced(
        self,
        class_container: dict,
    ) -> None:
        """Executions that exceed the timeout are terminated.

        Uses the entrypoint's JSON-RPC exec method with a 1s timeout,
        exercising the real ``ThreadTimeoutStrategy`` instead of the
        OS-level ``timeout`` command. The total wall time includes
        the entrypoint's hard_timeout (5s for thread cleanup), so
        total elapsed should be under 10s — still a 3x improvement
        over the baseline 30s.
        """
        container_id = class_container["container_id"]
        docker_client = docker.from_env()

        start = time.time()
        response = rpc_call(
            docker_client,
            container_id,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "exec",
                "params": {"code": "import time; time.sleep(60)", "timeout": 1.0},
            },
        )
        elapsed = time.time() - start

        result = response.get("result", response)
        # The timeout should fire within ~6s (1s execution timeout + 5s
        # hard_timeout for thread cleanup), well under 10s compared to
        # the baseline 15-30s.
        assert elapsed < 10.0, (
            f"Expected timeout enforcement within 10s, got {elapsed:.2f}s"
        )
        error = result.get("error", "")
        assert error is not None, f"Expected a timeout error, got: {result}"
        assert any(kw in error.lower() for kw in ["timed out", "timeout"]), (
            f"Expected timeout-related error, got: {error}"
        )

    def test_container_rpc_socket_timeout(
        self,
        class_container: dict,
    ) -> None:
        """``container_rpc`` raises ``ConnectionError`` when the socket times out.

        ``container_rpc`` sets ``sock.settimeout(10.0)`` on the attach socket.
        If the entrypoint takes longer than 10s to respond, ``read_frame``
        raises ``socket.timeout`` → ``ConnectionError``.

        We send an ``exec`` request with ``timeout=6.0`` and ``time.sleep(60)``
        — the entrypoint's ``ThreadTimeoutStrategy`` waits 6s then another 5s
        for hard timeout cleanup, totalling ~11s. Our socket timeout fires at
        10s.
        """
        container_id = class_container["container_id"]
        docker_client = docker.from_env()

        start = time.time()
        with pytest.raises(ConnectionError, match="No JSON-RPC response within"):
            rpc_call(
                docker_client,
                container_id,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "exec",
                    "params": {"code": "import time; time.sleep(60)", "timeout": 6.0},
                },
            )
        elapsed = time.time() - start

        # Socket timeout is 10s; allow some clock skew.
        assert elapsed < 14.0, (
            f"Expected socket timeout within ~10s, got {elapsed:.2f}s"
        )

    def test_display_hook_captures_expression_value(
        self,
        class_container: dict,
    ) -> None:
        """Expression that produces a value triggers sys.displayhook capture.

        Exercises the JSON-RPC stdin/stdout path through the entrypoint.
        The entrypoint uses 'single' compile mode so that expression values
        like `[1, 2, 3]` trigger sys.displayhook, which is captured to the
        `display` field in the response.
        """
        container_id = class_container["container_id"]
        docker_client = docker.from_env()

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

    def test_display_hook_captures_literal_value(
        self,
        class_container: dict,
    ) -> None:
        """Literal expressions like `42` produce display hook output."""
        container_id = class_container["container_id"]
        docker_client = docker.from_env()

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

    def test_namespace_reset_clears_session_state(
        self,
        class_container: dict,
    ) -> None:
        """Namespace reset clears all session state.

        Exercises the JSON-RPC stdin/stdout path: set a variable, verify it
        exists, send reset command, then verify the variable is gone.
        """
        container_id = class_container["container_id"]
        docker_client = docker.from_env()

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
