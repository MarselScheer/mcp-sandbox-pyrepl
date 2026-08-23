"""Tests for the SessionServer — the main JSON-RPC stdin/stdout loop.

The server receives stdin/stdout as injected dependencies (DI principle).
No mock.patch needed — arrange is 1-3 lines.

Assertions use parsed JSON (json.loads) rather than raw string matching,
so they verify behavior, not formatting.
"""

from __future__ import annotations

import json
from io import StringIO

from entrypoint import (
    RPCDispatcher,
    SessionServer,
)


class TestSessionServer:
    """Behavior-driven tests for the main JSON-RPC loop."""

    def _run_server(self, input_lines: str, dispatcher: RPCDispatcher) -> list[dict]:
        """Run the server with given input and return parsed response lines."""
        stdin = StringIO(input_lines)
        stdout = StringIO()
        server = SessionServer(
            dispatcher=dispatcher,
            stdin=stdin,
            stdout=stdout,
        )
        server.run()
        return [
            json.loads(line) for line in stdout.getvalue().strip().split("\n") if line
        ]

    def test_processes_single_request(self, stub_dispatcher: RPCDispatcher) -> None:
        responses = self._run_server(
            '{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}\n',
            stub_dispatcher,
        )

        assert len(responses) == 1
        assert responses[0]["jsonrpc"] == "2.0"
        assert responses[0]["id"] == 1
        assert responses[0]["result"] == {"ok": True}

    def test_processes_multiple_requests(self, stub_dispatcher: RPCDispatcher) -> None:
        responses = self._run_server(
            '{"jsonrpc":"2.0","id":1,"method":"exec","params":{"code":"x = 42"}}\n'
            '{"jsonrpc":"2.0","id":2,"method":"exec","params":{"code":"print(x)"}}\n',
            stub_dispatcher,
        )

        assert len(responses) == 2
        assert responses[0]["id"] == 1
        assert responses[1]["id"] == 2

    def test_shutdown_ends_loop(self, stub_dispatcher: RPCDispatcher) -> None:
        responses = self._run_server(
            '{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}\n'
            '{"jsonrpc":"2.0","id":2,"method":"shutdown","params":{}}\n'
            '{"jsonrpc":"2.0","id":3,"method":"ping","params":{}}\n',
            stub_dispatcher,
        )

        # Only 2 responses (shutdown stops the loop before the 3rd request)
        assert len(responses) == 2
        assert responses[0]["id"] == 1
        assert responses[1]["id"] == 2

    def test_skip_empty_lines(self, stub_dispatcher: RPCDispatcher) -> None:
        responses = self._run_server(
            '\n{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}\n',
            stub_dispatcher,
        )

        assert len(responses) == 1
        assert responses[0]["id"] == 1

    def test_skip_invalid_json_lines(self, stub_dispatcher: RPCDispatcher) -> None:
        responses = self._run_server(
            'not json\n{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}\n',
            stub_dispatcher,
        )

        assert len(responses) == 1
        assert responses[0]["id"] == 1

    def test_unknown_method_returns_error(self, stub_dispatcher: RPCDispatcher) -> None:
        responses = self._run_server(
            '{"jsonrpc":"2.0","id":1,"method":"unknown","params":{}}\n',
            stub_dispatcher,
        )

        assert len(responses) == 1
        assert responses[0]["error"]["code"] == -32601
        assert "unknown" in responses[0]["error"]["message"]

    def test_each_line_is_independently_valid_json(
        self, stub_dispatcher: RPCDispatcher
    ) -> None:
        responses = self._run_server(
            '{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}\n'
            '{"jsonrpc":"2.0","id":2,"method":"ping","params":{}}\n',
            stub_dispatcher,
        )

        assert len(responses) == 2
        for response in responses:
            assert "jsonrpc" in response
            assert "id" in response
