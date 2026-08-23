"""Tests for the JSON-RPC dispatcher — the routing layer.

The dispatcher is composed of injectable collaborators (Namespace, TimeoutStrategy,
PackageInstaller). We use fakes to keep the arrange phase at 1-3 lines.
"""

from __future__ import annotations

from entrypoint import (
    ExecResult,
    Namespace,
    NoOpTimeoutStrategy,
    RPCDispatcher,
    RPCDispatcherConfig,
    RPCRequest,
)

from .conftest import FakePackageInstaller

# ──────────────────────────────────────────────────────────────────────
# Fakes
# ──────────────────────────────────────────────────────────────────────


class FakeTimeoutStrategy:
    """A fake timeout strategy for testing — no threads, no real time.

    The arrange phase stays at 1 line: FakeTimeoutStrategy()
    """

    def __init__(self, result: ExecResult | None = None) -> None:
        self._result = result
        self.last_code: str = ""
        self.last_timeout: float = 0.0

    def execute_with_timeout(
        self, namespace: Namespace, code: str, timeout: float
    ) -> ExecResult:
        self.last_code = code
        self.last_timeout = timeout
        if self._result is not None:
            return self._result
        return namespace.exec(code)


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


class TestRPCDispatcherRouting:
    """The dispatcher routes method names to handler implementations."""

    def test_exec_method_routes_to_namespace(self) -> None:
        timeout = FakeTimeoutStrategy()
        dispatcher = RPCDispatcher(
            namespace=Namespace(),
            timeout_strategy=timeout,
            installer=FakePackageInstaller(),
            config=RPCDispatcherConfig(),
        )

        request = RPCRequest(id=1, method="exec", params={"code": "2 + 2"})
        response = dispatcher.handle(request)

        assert response["id"] == 1
        assert response["result"]["display"] == ["4"]
        assert timeout.last_code == "2 + 2"

    def test_reset_method(self) -> None:
        namespace = Namespace()
        dispatcher = RPCDispatcher(
            namespace=namespace,
            timeout_strategy=NoOpTimeoutStrategy(),
            installer=FakePackageInstaller(),
            config=RPCDispatcherConfig(),
        )

        namespace.exec("x = 42")
        request = RPCRequest(id=2, method="reset", params={})
        response = dispatcher.handle(request)

        assert response["result"]["ok"] is True

        # Verify namespace was actually reset
        result = namespace.exec("print(x)")
        assert "NameError" in result.error

    def test_ping_method(self, stub_dispatcher: RPCDispatcher) -> None:
        request = RPCRequest(id=3, method="ping", params={})
        response = stub_dispatcher.handle(request)

        assert response["result"]["ok"] is True

    def test_shutdown_method(self, stub_dispatcher: RPCDispatcher) -> None:
        request = RPCRequest(id=4, method="shutdown", params={})
        response = stub_dispatcher.handle(request)

        assert response["result"]["ok"] is True
        assert stub_dispatcher.shutdown_requested is True

    def test_unknown_method_returns_error(self, stub_dispatcher: RPCDispatcher) -> None:
        request = RPCRequest(id=5, method="nonexistent", params={})
        response = stub_dispatcher.handle(request)

        assert "error" in response
        assert response["error"]["code"] == -32601
        assert "nonexistent" in response["error"]["message"]

    def test_install_method_routes_to_installer(self) -> None:
        installer = FakePackageInstaller()
        dispatcher = RPCDispatcher(
            namespace=Namespace(),
            timeout_strategy=NoOpTimeoutStrategy(),
            installer=installer,
            config=RPCDispatcherConfig(),
        )

        request = RPCRequest(
            id=6,
            method="install",
            params={"packages": [{"name": "pandas"}]},
        )
        response = dispatcher.handle(request)

        assert response["result"]["stdout"] == "Installed 1 package(s)"
        assert installer.last_packages == [{"name": "pandas"}]


class TestRPCDispatcherExec:
    """Exec method behavior through the dispatcher."""

    def test_exec_with_custom_timeout(self) -> None:
        timeout = FakeTimeoutStrategy()
        dispatcher = RPCDispatcher(
            namespace=Namespace(),
            timeout_strategy=timeout,
            installer=FakePackageInstaller(),
            config=RPCDispatcherConfig(),
        )

        request = RPCRequest(
            id=1,
            method="exec",
            params={"code": "print('hi')", "timeout": 15},
        )
        dispatcher.handle(request)

        assert timeout.last_timeout == 15.0

    def test_exec_with_default_timeout(self) -> None:
        config = RPCDispatcherConfig(default_timeout=30.0)
        timeout = FakeTimeoutStrategy()
        dispatcher = RPCDispatcher(
            namespace=Namespace(),
            timeout_strategy=timeout,
            installer=FakePackageInstaller(),
            config=config,
        )

        request = RPCRequest(
            id=1,
            method="exec",
            params={"code": "print('hi')"},
        )
        dispatcher.handle(request)

        assert timeout.last_timeout == 30.0

    def test_exec_returns_session_corrupted_flag(self) -> None:
        timeout = FakeTimeoutStrategy(
            result=ExecResult(error="Timed out", session_corrupted=True)
        )
        dispatcher = RPCDispatcher(
            namespace=Namespace(),
            timeout_strategy=timeout,
            installer=FakePackageInstaller(),
            config=RPCDispatcherConfig(),
        )

        request = RPCRequest(id=1, method="exec", params={"code": "sleep(999)"})
        response = dispatcher.handle(request)

        assert response["result"]["session_corrupted"] is True
        assert "Timed out" in response["result"]["error"]


class TestRPCDispatcherRequestParsing:
    """Parsing JSON-RPC 2.0 requests from raw lines."""

    def test_parse_valid_request(self) -> None:
        request = RPCDispatcher._parse_line(
            '{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}'
        )

        assert request is not None
        assert request.id == 1
        assert request.method == "ping"
        assert request.params == {}

    def test_parse_invalid_json(self) -> None:
        request = RPCDispatcher._parse_line("not json")

        assert request is None

    def test_parse_empty_method(self) -> None:
        request = RPCDispatcher._parse_line(
            '{"jsonrpc":"2.0","id":1,"method":"","params":{}}'
        )

        assert request is None

    def test_parse_request_without_id(self) -> None:
        request = RPCDispatcher._parse_line(
            '{"jsonrpc":"2.0","method":"ping","params":{}}'
        )

        assert request is not None
        assert request.id is None
        assert request.method == "ping"


class TestRPCDispatcherResponseBuilding:
    """Building JSON-RPC 2.0 responses."""

    def test_success_response(self) -> None:
        response = RPCDispatcher._success_response(1, {"ok": True})

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert response["result"] == {"ok": True}

    def test_error_response(self) -> None:
        response = RPCDispatcher._error_response(1, -32601, "Method not found")

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert response["error"]["code"] == -32601
        assert response["error"]["message"] == "Method not found"

    def test_success_response_with_null_id(self) -> None:
        response = RPCDispatcher._success_response(None, {"ok": True})

        assert response["id"] is None
